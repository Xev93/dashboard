from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ai_dashboard.source_catalog import ENGAGEMENT_KEYS as _ENGAGEMENT_KEYS
from ai_dashboard.storage.models import FeedItem, _parse_iso


SCHEMA_VERSION = 2
MIN_SAMPLE_SIZE = 20


SCHEMA_V1_SQL = """
CREATE TABLE IF NOT EXISTS feed_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_uid  TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    published_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    seen        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE(source_kind, source_uid)
);

CREATE INDEX IF NOT EXISTS idx_feed_items_published ON feed_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_items_source ON feed_items(source_kind);

CREATE TABLE IF NOT EXISTS sources (
    kind                 TEXT PRIMARY KEY,
    last_fetched         TEXT,
    next_fetch           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_cache (
    source_kind TEXT NOT NULL,
    source_uid  TEXT NOT NULL,
    content     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source_kind, source_uid)
);
"""


SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS user_search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    searched_at REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_search_history_term ON user_search_history(term);
CREATE INDEX IF NOT EXISTS idx_search_history_time ON user_search_history(searched_at);

CREATE TABLE IF NOT EXISTS item_view_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_uid TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('viewed', 'skipped')),
    logged_at REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_view_log_action ON item_view_log(action, logged_at);
CREATE INDEX IF NOT EXISTS idx_view_log_source ON item_view_log(source_kind, logged_at);

UPDATE schema_version SET version = 2;
"""


class Database:
    """Single-connection async SQLite wrapper with WAL mode.

    This class owns exactly one aiosqlite.Connection for the App lifetime.
    Do not instantiate more than one Database per SQLite file — WAL coherency
    relies on per-connection state. See ADR-5 in the implementation plan.
    """

    _VALID_VIEW_ACTIONS: frozenset[str] = frozenset({"viewed", "skipped"})

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.commit()
            finally:
                await self._conn.close()
                self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def init_schema(self) -> None:
        conn = self.connection
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        )
        has_schema_version_table = await cursor.fetchone() is not None
        await cursor.close()

        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL DEFAULT 1)"
        )
        if not has_schema_version_table:
            await conn.execute("INSERT INTO schema_version(version) VALUES (1)")

        await conn.executescript(SCHEMA_V1_SQL)
        cursor = await conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = await cursor.fetchone()
        await cursor.close()
        version = row["version"] if row else 1
        if version < 2:
            await conn.executescript(SCHEMA_V2_SQL)
        await conn.commit()
        await self.evict_stale_cache()

    async def upsert_items(self, items: list[FeedItem]) -> int:
        if not items:
            return 0
        conn = self.connection
        new_count = 0
        for item in items:
            insert_cursor = await conn.execute(
                """
                INSERT OR IGNORE INTO feed_items
                    (source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item.to_row(),
            )
            was_inserted = insert_cursor.rowcount == 1
            await insert_cursor.close()

            if was_inserted:
                new_count += 1
            else:
                payload_json = json.dumps(
                    item.raw_payload, separators=(",", ":"), ensure_ascii=False
                )
                update_cursor = await conn.execute(
                    """
                    UPDATE feed_items
                    SET title = ?, url = ?, raw_payload = ?
                    WHERE source_kind = ? AND source_uid = ?
                    """,
                    (
                        item.title,
                        item.url,
                        payload_json,
                        item.source_kind,
                        item.source_uid,
                    ),
                )
                await update_cursor.close()
        await conn.commit()
        return new_count

    async def get_items(
        self, limit: int = 500, source_kind: str | None = None
    ) -> list[FeedItem]:
        conn = self.connection
        if source_kind is not None:
            sql = """
                SELECT id, source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at
                FROM feed_items
                WHERE source_kind = ?
                ORDER BY published_at DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (source_kind, limit)
        else:
            sql = """
                SELECT id, source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at
                FROM feed_items
                ORDER BY published_at DESC
                LIMIT ?
            """
            params = (limit,)
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FeedItem.from_row(row) for row in rows]

    async def mark_seen(self, item_id: int, seen: bool = True) -> None:
        conn = self.connection
        await conn.execute(
            "UPDATE feed_items SET seen = ? WHERE id = ?",
            (1 if seen else 0, item_id),
        )
        await conn.commit()

    async def record_item_view(
        self, source_kind: str, source_uid: str, action: str
    ) -> None:
        """Record a viewed or skipped action for ranking."""
        if action not in self._VALID_VIEW_ACTIONS:
            raise ValueError(
                f"Invalid action {action!r}, must be one of {sorted(self._VALID_VIEW_ACTIONS)}"
            )
        conn = self.connection
        await conn.execute(
            "INSERT INTO item_view_log (source_kind, source_uid, action) VALUES (?, ?, ?)",
            (source_kind, source_uid, action),
        )
        await conn.commit()

    async def record_search_term(self, term: str) -> None:
        """Record a search term for keyword_boost ranking."""
        conn = self.connection
        await conn.execute(
            "INSERT INTO user_search_history (term) VALUES (?)",
            (term,),
        )
        await conn.commit()

    async def get_top_search_terms(self, limit: int = 10) -> list[str]:
        """Get the most recent unique search terms for keyword_boost."""
        conn = self.connection
        cursor = await conn.execute(
            "SELECT DISTINCT term FROM user_search_history ORDER BY searched_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

    async def get_skip_counts(self, last_n_views: int = 50) -> dict[str, int]:
        """Count skips per source_kind in the last N view log entries.

        Returns dict mapping source_kind → skip count.
        """
        conn = self.connection
        cursor = await conn.execute(
            """
            SELECT source_kind, COUNT(*) as cnt
            FROM (
                SELECT source_kind, action FROM item_view_log
                ORDER BY logged_at DESC LIMIT ?
            ) WHERE action = 'skipped'
            GROUP BY source_kind
            """,
            (last_n_views,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {row[0]: row[1] for row in rows}

    async def get_engagement_percentiles(self) -> dict[str, float]:
        default_p95 = {
            "hn": 500.0,
            "github_trending": 10000.0,
            "reddit": 1000.0,
            "huggingface": 5000.0,
        }
        conn = self.connection
        result: dict[str, float] = {
            kind: default_p95.get(kind, 1.0) for kind in _ENGAGEMENT_KEYS
        }
        query_parts: list[str] = []
        params: list[str] = []

        for kind, json_key in _ENGAGEMENT_KEYS.items():
            json_path = f"$.{json_key}"
            query_parts.append(
                """
                SELECT ? AS source_kind, CAST(json_extract(raw_payload, ?) AS REAL) AS val
                FROM feed_items
                WHERE source_kind = ? AND json_extract(raw_payload, ?) IS NOT NULL
                """
            )
            params.extend((kind, json_path, kind, json_path))

        cursor = await conn.execute(
            f"""
            WITH engagement_values AS (
                {" UNION ALL ".join(query_parts)}
            ),
            ranked_values AS (
                SELECT
                    source_kind,
                    val,
                    COUNT(*) OVER (PARTITION BY source_kind) AS cnt,
                    ROW_NUMBER() OVER (PARTITION BY source_kind ORDER BY val ASC) - 1 AS idx
                FROM engagement_values
            )
            SELECT source_kind, cnt, val AS p95
            FROM ranked_values
            WHERE idx = MIN(CAST(cnt * 0.95 AS INTEGER), cnt - 1)
            """,
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()

        for row in rows:
            if row["cnt"] >= MIN_SAMPLE_SIZE and row["p95"] is not None:
                result[row["source_kind"]] = max(float(row["p95"]), 1.0)

        return result

    async def get_user_state(self, key: str) -> str | None:
        conn = self.connection
        cursor = await conn.execute(
            "SELECT value FROM user_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row["value"] if row else None

    async def set_user_state(self, key: str, value: str) -> None:
        conn = self.connection
        await conn.execute(
            """
            INSERT INTO user_state(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await conn.commit()

    async def get_cached_content(self, source_kind: str, source_uid: str) -> str | None:
        conn = self.connection
        cursor = await conn.execute(
            "SELECT content FROM content_cache WHERE source_kind = ? AND source_uid = ?",
            (source_kind, source_uid),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row["content"] if row else None

    async def evict_stale_cache(self, max_age_days: int = 30) -> int:
        conn = self.connection
        cursor = await conn.execute(
            "DELETE FROM content_cache WHERE fetched_at < unixepoch('now') - ? * 86400",
            (max_age_days,),
        )
        await conn.commit()
        return cursor.rowcount

    async def set_cached_content(
        self, source_kind: str, source_uid: str, content: str
    ) -> None:
        conn = self.connection
        await conn.execute(
            """
            INSERT INTO content_cache(source_kind, source_uid, content, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_kind, source_uid) DO UPDATE SET
                content = excluded.content,
                fetched_at = excluded.fetched_at
            """,
            (source_kind, source_uid, content, datetime.now(timezone.utc).isoformat()),
        )
        await conn.commit()

    async def get_source_state(self, kind: str) -> dict[str, Any] | None:
        conn = self.connection
        cursor = await conn.execute(
            "SELECT kind, last_fetched, next_fetch, consecutive_failures FROM sources WHERE kind = ?",
            (kind,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "kind": row["kind"],
            "last_fetched": row["last_fetched"],
            "next_fetch": row["next_fetch"],
            "consecutive_failures": row["consecutive_failures"],
        }

    async def update_source_state(
        self,
        kind: str,
        *,
        last_fetched: datetime | None = None,
        next_fetch: datetime | None = None,
        consecutive_failures: int | None = None,
    ) -> None:
        conn = self.connection
        existing = await self.get_source_state(kind)
        if existing is None:
            await conn.execute(
                "INSERT INTO sources(kind, last_fetched, next_fetch, consecutive_failures) VALUES(?, ?, ?, ?)",
                (
                    kind,
                    last_fetched.isoformat() if last_fetched else None,
                    next_fetch.isoformat() if next_fetch else None,
                    consecutive_failures if consecutive_failures is not None else 0,
                ),
            )
        else:
            await conn.execute(
                """UPDATE sources SET
                    last_fetched = COALESCE(?, last_fetched),
                    next_fetch = COALESCE(?, next_fetch),
                    consecutive_failures = COALESCE(?, consecutive_failures)
                WHERE kind = ?""",
                (
                    last_fetched.isoformat() if last_fetched is not None else None,
                    next_fetch.isoformat() if next_fetch is not None else None,
                    consecutive_failures,
                    kind,
                ),
            )
        await conn.commit()

    _ALLOWED_PRAGMAS: frozenset[str] = frozenset(
        {
            "journal_mode",
            "busy_timeout",
            "synchronous",
            "wal_checkpoint",
            "integrity_check",
            "foreign_keys",
            "user_version",
            "page_size",
            "cache_size",
            "table_info",
        }
    )

    async def pragma(self, name: str) -> Any:
        if name not in self._ALLOWED_PRAGMAS:
            raise ValueError(
                f"PRAGMA {name!r} not in allowlist: {sorted(self._ALLOWED_PRAGMAS)}"
            )
        conn = self.connection
        cursor = await conn.execute(f"PRAGMA {name}")
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None
