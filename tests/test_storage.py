from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


@pytest.mark.asyncio
async def test_wal_mode_enabled(db: Database) -> None:
    assert (await db.pragma("journal_mode")).lower() == "wal"


@pytest.mark.asyncio
async def test_init_schema_idempotent(db: Database) -> None:
    await db.init_schema()
    await db.init_schema()


@pytest.mark.asyncio
async def test_upsert_returns_new_count_then_zero(db: Database) -> None:
    item = FeedItem(
        id=None,
        source_kind="arxiv",
        source_uid="1",
        title="Title 1",
        url="https://example.com/1",
        published_at=datetime(2026, 4, 11, 10, 0, tzinfo=timezone.utc),
        raw_payload={"x": 1},
    )
    assert await db.upsert_items([item]) == 1
    assert await db.upsert_items([item]) == 0


@pytest.mark.asyncio
async def test_upsert_updates_existing_fields(db: Database) -> None:
    original = FeedItem(
        id=None,
        source_kind="arxiv",
        source_uid="1",
        title="Original title",
        url="https://example.com/1",
        published_at=datetime(2026, 4, 11, 10, 0, tzinfo=timezone.utc),
        raw_payload={"x": 1},
    )
    updated = FeedItem(
        id=None,
        source_kind="arxiv",
        source_uid="1",
        title="New title",
        url="https://example.com/1",
        published_at=datetime(2026, 4, 11, 11, 0, tzinfo=timezone.utc),
        raw_payload={"x": 2},
    )
    await db.upsert_items([original])
    await db.upsert_items([updated])
    items = await db.get_items()
    assert items[0].title == "New title"


@pytest.mark.asyncio
async def test_get_items_returns_empty_on_fresh_db(db: Database) -> None:
    assert await db.get_items() == []


@pytest.mark.asyncio
async def test_get_items_orders_by_published_desc(db: Database) -> None:
    items = [
        FeedItem(
            id=None,
            source_kind="arxiv",
            source_uid=str(i),
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 4, 11, 10 + i, tzinfo=timezone.utc),
            raw_payload={"i": i},
        )
        for i in range(3)
    ]
    await db.upsert_items(items)
    ordered = await db.get_items()
    assert [item.source_uid for item in ordered] == ["2", "1", "0"]


@pytest.mark.asyncio
async def test_get_items_limit(db: Database) -> None:
    items = [
        FeedItem(
            id=None,
            source_kind="arxiv",
            source_uid=str(i),
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 4, 11, 10 + i, tzinfo=timezone.utc),
            raw_payload={"i": i},
        )
        for i in range(5)
    ]
    await db.upsert_items(items)
    assert len(await db.get_items(limit=2)) == 2


@pytest.mark.asyncio
async def test_get_items_filter_by_source_kind(db: Database) -> None:
    items = [
        FeedItem(
            id=None,
            source_kind="arxiv" if i % 2 == 0 else "hn",
            source_uid=str(i),
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 4, 11, 10 + i, tzinfo=timezone.utc),
            raw_payload={"i": i},
        )
        for i in range(4)
    ]
    await db.upsert_items(items)
    filtered = await db.get_items(source_kind="arxiv")
    assert filtered and all(item.source_kind == "arxiv" for item in filtered)


@pytest.mark.asyncio
async def test_mark_seen(db: Database) -> None:
    await db.upsert_items(
        [
            FeedItem(
                id=None,
                source_kind="arxiv",
                source_uid="1",
                title="Title 1",
                url="https://example.com/1",
                published_at=datetime(2026, 4, 11, 10, 0, tzinfo=timezone.utc),
                raw_payload={"x": 1},
            )
        ]
    )
    item_id = (await db.get_items())[0].id
    assert item_id is not None
    await db.mark_seen(item_id)
    assert (await db.get_items())[0].seen is True


@pytest.mark.asyncio
async def test_user_state_get_set(db: Database) -> None:
    await db.set_user_state("last_check", "2026-04-11T00:00:00Z")
    assert await db.get_user_state("last_check") == "2026-04-11T00:00:00Z"
    assert await db.get_user_state("missing") is None


@pytest.mark.asyncio
async def test_source_state_update(db: Database) -> None:
    now = datetime.now(timezone.utc)
    await db.update_source_state(
        "arxiv",
        last_fetched=now,
        consecutive_failures=3,
    )
    state = await db.get_source_state("arxiv")
    assert state is not None
    assert state["consecutive_failures"] == 3
