from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS feed_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_uid TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(source_kind, source_uid)
);

CREATE TABLE IF NOT EXISTS user_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL DEFAULT 1
);
"""


async def _table_exists(db: Database, table_name: str) -> bool:
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return row is not None


async def _schema_version(db: Database) -> int:
    cursor = await db.connection.execute("SELECT version FROM schema_version LIMIT 1")
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    return int(row["version"])


async def _insert_search_history(
    db: Database, entries: list[tuple[str, float]]
) -> None:
    _ = await db.connection.executemany(
        "INSERT INTO user_search_history(term, searched_at) VALUES (?, ?)",
        entries,
    )
    await db.connection.commit()


async def _insert_view_log(
    db: Database, entries: list[tuple[str, str, str, float]]
) -> None:
    _ = await db.connection.executemany(
        """
        INSERT INTO item_view_log(source_kind, source_uid, action, logged_at)
        VALUES (?, ?, ?, ?)
        """,
        entries,
    )
    await db.connection.commit()


def _make_item(source_uid: str, title: str = "Item") -> FeedItem:
    return FeedItem(
        id=None,
        source_kind="hn",
        source_uid=source_uid,
        title=title,
        url=f"https://example.com/{source_uid}",
        published_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        raw_payload={},
    )


@pytest.mark.asyncio
async def test_fresh_db_creates_v4_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()

        assert await _schema_version(db) == 4
        assert await _table_exists(db, "user_search_history") is True
        assert await _table_exists(db, "item_view_log") is True
        assert await _table_exists(db, "rank_history") is True

        cursor = await db.connection.execute("PRAGMA table_info(feed_items)")
        columns = await cursor.fetchall()
        await cursor.close()
        assert any(column[1] == "sentiment" for column in columns)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_v1_db_migrates_to_v4(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        _ = await db.connection.executescript(V1_SCHEMA_SQL)
        _ = await db.connection.execute(
            "INSERT INTO schema_version(version) VALUES (1)"
        )
        _ = await db.connection.execute(
            """
            INSERT INTO feed_items(
                source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "arxiv",
                "paper-1",
                "Original title",
                "https://example.com/paper-1",
                "2026-04-12T00:00:00+00:00",
                "{}",
                0,
                "2026-04-12T00:00:00+00:00",
            ),
        )
        _ = await db.connection.execute(
            "INSERT INTO user_state(key, value) VALUES (?, ?)",
            ("last_search", "transformers"),
        )
        await db.connection.commit()

        await db.init_schema()

        assert await _schema_version(db) == 4
        assert await _table_exists(db, "user_search_history") is True
        assert await _table_exists(db, "item_view_log") is True
        assert await _table_exists(db, "rank_history") is True

        cursor = await db.connection.execute(
            "SELECT title, sentiment FROM feed_items WHERE source_kind = ? AND source_uid = ?",
            ("arxiv", "paper-1"),
        )
        feed_row = await cursor.fetchone()
        await cursor.close()

        cursor = await db.connection.execute(
            "SELECT value FROM user_state WHERE key = ?",
            ("last_search",),
        )
        state_row = await cursor.fetchone()
        await cursor.close()

        assert feed_row is not None
        assert feed_row["title"] == "Original title"
        assert feed_row["sentiment"] is None
        assert state_row is not None
        assert state_row["value"] == "transformers"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_v4_db_no_double_migration(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await db.init_schema()

        assert await _schema_version(db) == 4

        cursor = await db.connection.execute("SELECT COUNT(*) FROM schema_version")
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert row[0] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_rankings_and_get_trajectory(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()

        alpha = _make_item("alpha", "Alpha")
        beta = _make_item("beta", "Beta")

        await db.record_rankings([alpha, beta])
        assert await db.get_rank_trajectory("hn", "alpha") == "🆕"

        await db.record_rankings([beta, alpha])

        assert await db.get_rank_trajectory("hn", "alpha") == "▼"
        assert await db.get_rank_trajectory("hn", "beta") == "▲"
        assert await db.get_bulk_trajectories([alpha, beta]) == {
            "alpha": "▼",
            "beta": "▲",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_rankings_prunes_old_polls(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        item = _make_item("alpha", "Alpha")

        for _ in range(12):
            await db.record_rankings([item])
            _ = await db.connection.execute(
                "UPDATE rank_history SET polled_at = polled_at + 1 WHERE id = last_insert_rowid()"
            )
            await db.connection.commit()

        cursor = await db.connection.execute(
            "SELECT COUNT(DISTINCT polled_at) AS polls FROM rank_history"
        )
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert row["polls"] == 10
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_viewed(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await db.record_item_view("arxiv", "paper-1", "viewed")

        cursor = await db.connection.execute(
            "SELECT source_kind, source_uid, action FROM item_view_log"
        )
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert dict(row) == {
            "source_kind": "arxiv",
            "source_uid": "paper-1",
            "action": "viewed",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_skipped(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await db.record_item_view("hn", "item-1", "skipped")

        cursor = await db.connection.execute(
            "SELECT source_kind, source_uid, action FROM item_view_log"
        )
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert dict(row) == {
            "source_kind": "hn",
            "source_uid": "item-1",
            "action": "skipped",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_invalid_action(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()

        with pytest.raises(ValueError):
            await db.record_item_view("hn", "item-1", "other")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_search_term(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await db.record_search_term("agents")

        cursor = await db.connection.execute("SELECT term FROM user_search_history")
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert row["term"] == "agents"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_multiple_terms(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        for term in ["agents", "ranking", "sqlite"]:
            await db.record_search_term(term)

        cursor = await db.connection.execute(
            "SELECT term FROM user_search_history ORDER BY id"
        )
        rows = await cursor.fetchall()
        await cursor.close()

        assert [row["term"] for row in rows] == ["agents", "ranking", "sqlite"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_top_search_terms_empty(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()

        assert await db.get_top_search_terms() == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_top_search_terms_returns_recent(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await _insert_search_history(
            db,
            [
                ("alpha", 1.0),
                ("beta", 2.0),
                ("gamma", 3.0),
                ("delta", 4.0),
                ("epsilon", 5.0),
            ],
        )

        assert await db.get_top_search_terms(3) == ["epsilon", "delta", "gamma"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_top_search_terms_deduplicates(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await _insert_search_history(db, [("agents", 1.0), ("agents", 2.0)])

        assert await db.get_top_search_terms() == ["agents"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_skip_counts_empty(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()

        assert await db.get_skip_counts() == {}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_skip_counts_counts_skips(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        await _insert_view_log(
            db,
            [
                ("arxiv", "1", "viewed", 1.0),
                ("arxiv", "2", "skipped", 2.0),
                ("hn", "3", "skipped", 3.0),
                ("hn", "4", "viewed", 4.0),
                ("hn", "5", "skipped", 5.0),
            ],
        )

        assert await db.get_skip_counts() == {"arxiv": 1, "hn": 2}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_get_skip_counts_respects_window(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        await db.init_schema()
        entries: list[tuple[str, str, str, float]] = []
        for index in range(10):
            entries.append(("arxiv", f"old-skip-{index}", "skipped", float(index + 1)))
        for index in range(20):
            entries.append(("hn", f"recent-skip-{index}", "skipped", float(index + 11)))
        for index in range(30):
            entries.append(
                ("arxiv", f"recent-view-{index}", "viewed", float(index + 31))
            )

        await _insert_view_log(db, entries)

        assert await db.get_skip_counts(50) == {"hn": 20}
    finally:
        await db.close()
