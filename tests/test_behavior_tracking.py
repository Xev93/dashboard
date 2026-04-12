from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from textual.widgets import DataTable

from ai_dashboard.app import AIDashboardApp
from ai_dashboard.config import AppConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.widgets.feed_list import FeedListWidget


class DummyStrategy:
    name = "dummy"

    def __init__(self, items: list[FeedItem]) -> None:
        self._items = items

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        _ = (db, now)
        return self._items


def make_item(source_uid: str, *, source_kind: str = "hn", points: int = 0) -> FeedItem:
    return FeedItem(
        id=None,
        source_kind=source_kind,
        source_uid=source_uid,
        title=f"Item {source_uid}",
        url=f"https://example.com/{source_uid}",
        published_at=datetime(2026, 4, 11, 10, 0, tzinfo=timezone.utc),
        raw_payload={"points": points},
    )


def make_config(tmp_path: Path) -> AppConfig:
    config = AppConfig.defaults()
    config.db_path = tmp_path / "behavior-tracking.db"
    return config


def make_widget(db: Database, items: list[FeedItem]) -> FeedListWidget:
    widget = FeedListWidget(DummyStrategy(items), db)
    widget._items = items
    return widget


def highlighted_event(cursor_row: int) -> DataTable.RowHighlighted:
    return cast(
        DataTable.RowHighlighted,
        cast(object, SimpleNamespace(cursor_row=cursor_row)),
    )


def test_dwell_viewed(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [make_item("1"), make_item("2")]
    widget = make_widget(db, items)
    messages: list[object] = []
    monkeypatch.setattr(widget, "post_message", messages.append)
    times = iter([10.0, 12.1])
    monkeypatch.setattr(
        "ai_dashboard.widgets.feed_list.time.monotonic", lambda: next(times)
    )

    widget.on_data_table_row_highlighted(highlighted_event(0))
    widget.on_data_table_row_highlighted(highlighted_event(1))

    assert any(
        isinstance(message, FeedListWidget.ItemViewed) and message.item == items[0]
        for message in messages
    )


def test_dwell_skipped(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [make_item("1"), make_item("2")]
    widget = make_widget(db, items)
    messages: list[object] = []
    monkeypatch.setattr(widget, "post_message", messages.append)
    times = iter([20.0, 21.5])
    monkeypatch.setattr(
        "ai_dashboard.widgets.feed_list.time.monotonic", lambda: next(times)
    )

    widget.on_data_table_row_highlighted(highlighted_event(0))
    widget.on_data_table_row_highlighted(highlighted_event(1))

    assert any(
        isinstance(message, FeedListWidget.ItemSkipped) and message.item == items[0]
        for message in messages
    )


def test_item_selected_still_fires(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [make_item("1"), make_item("2")]
    widget = make_widget(db, items)
    messages: list[object] = []
    monkeypatch.setattr(widget, "post_message", messages.append)
    times = iter([30.0, 31.0])
    monkeypatch.setattr(
        "ai_dashboard.widgets.feed_list.time.monotonic", lambda: next(times)
    )

    widget.on_data_table_row_highlighted(highlighted_event(0))
    widget.on_data_table_row_highlighted(highlighted_event(1))

    selected = [
        message
        for message in messages
        if isinstance(message, FeedListWidget.ItemSelected)
    ]
    assert len(selected) == 2
    assert [message.item for message in selected] == items


@pytest.mark.asyncio
async def test_view_recorded_to_db(tmp_path: Path) -> None:
    app = AIDashboardApp(make_config(tmp_path))
    mock_db = AsyncMock()
    object.__setattr__(app, "db", mock_db)
    item = make_item("1")

    await app.on_feed_list_widget_item_viewed(FeedListWidget.ItemViewed(item))

    mock_db.record_item_view.assert_awaited_once_with("hn", "1", "viewed")


@pytest.mark.asyncio
async def test_skip_recorded_to_db(tmp_path: Path) -> None:
    app = AIDashboardApp(make_config(tmp_path))
    mock_db = AsyncMock()
    object.__setattr__(app, "db", mock_db)
    item = make_item("2")

    await app.on_feed_list_widget_item_skipped(FeedListWidget.ItemSkipped(item))

    mock_db.record_item_view.assert_awaited_once_with("hn", "2", "skipped")


@pytest.mark.asyncio
async def test_engagement_percentiles_min_sample(db: Database) -> None:
    items = [make_item(str(i), points=i + 1) for i in range(19)]
    await db.upsert_items(items)

    percentiles = await db.get_engagement_percentiles()

    assert percentiles["hn"] == 500.0
    assert percentiles["github_trending"] == 10000.0


@pytest.mark.asyncio
async def test_engagement_percentiles_computed(db: Database) -> None:
    items = [make_item(str(i), points=i + 1) for i in range(20)]
    await db.upsert_items(items)

    percentiles = await db.get_engagement_percentiles()

    assert percentiles["hn"] == 20.0
    assert percentiles["reddit"] == 1000.0
