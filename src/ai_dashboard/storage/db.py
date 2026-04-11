from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ai_dashboard.storage.models import FeedItem, _parse_iso


SCHEMA_VERSION = 1


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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
"""


class Database:
    """Single-connection async SQLite wrapper with WAL mode.

    This class owns exactly one aiosqlite.Connection for the App lifetime.
    Do not instantiate more than one Database per SQLite file — WAL coherency
    relies on per-connection state. See ADR-5 in the implementation plan.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
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
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def init_schema(self) -> None:
        conn = self.connection
        await conn.executescript(SCHEMA_V1_SQL)
        await conn.commit()

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
                    SET title = ?, url = ?, published_at = ?, raw_payload = ?
                    WHERE source_kind = ? AND source_uid = ?
                    """,
                    (
                        item.title,
                        item.url,
                        item.published_at.isoformat(),
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
            sets: list[str] = []
            params: list[Any] = []
            if last_fetched is not None:
                sets.append("last_fetched = ?")
                params.append(last_fetched.isoformat())
            if next_fetch is not None:
                sets.append("next_fetch = ?")
                params.append(next_fetch.isoformat())
            if consecutive_failures is not None:
                sets.append("consecutive_failures = ?")
                params.append(consecutive_failures)
            if sets:
                params.append(kind)
                await conn.execute(
                    f"UPDATE sources SET {', '.join(sets)} WHERE kind = ?",
                    tuple(params),
                )
        await conn.commit()

    async def pragma(self, name: str) -> Any:
        conn = self.connection
        cursor = await conn.execute(f"PRAGMA {name}")
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None
