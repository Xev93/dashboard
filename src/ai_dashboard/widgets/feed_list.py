from __future__ import annotations

import time
from datetime import datetime, timezone
from importlib import import_module

from textual.message import Message
from textual.widgets import DataTable

from ai_dashboard.source_catalog import CATALOG_BY_KIND
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy


class FeedListWidget(DataTable[str]):
    class ItemSelected(Message):
        item: FeedItem

        def __init__(self, item: FeedItem) -> None:
            super().__init__()
            self.item = item

    class ItemViewed(Message):
        """Emitted when user dwells on item ≥2 seconds."""

        item: FeedItem

        def __init__(self, item: FeedItem) -> None:
            super().__init__()
            self.item = item

    class ItemSkipped(Message):
        """Emitted when user moves off item in <2 seconds."""

        item: FeedItem

        def __init__(self, item: FeedItem) -> None:
            super().__init__()
            self.item = item

    class ToggleRead(Message):
        item: FeedItem

        def __init__(self, item: FeedItem) -> None:
            super().__init__()
            self.item = item

    def __init__(
        self,
        strategy: FeedListStrategy,
        db: Database,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, cursor_type="row", zebra_stripes=True)
        self.strategy = strategy
        self.db = db
        self._items: list[FeedItem] = []
        self._current_item: FeedItem | None = None
        self._highlight_time: float = 0.0

    def on_mount(self) -> None:
        self.add_column("S", key="source")
        self.add_column("↕", key="trajectory", width=2)
        self.add_column("Title", key="title")
        self.add_column("Age", key="age")

    async def refresh_items(self, *, hide_read: bool = False) -> None:
        now = datetime.now(timezone.utc)
        items = await self.strategy.items(self.db, now)
        self._items = [item for item in items if not (hide_read and item.seen)]
        trajectories: dict[str, str] = {}
        if self._items:
            await self.db.record_rankings(self._items)
            trajectories = await self.db.get_bulk_trajectories(self._items)
        self.clear()
        for item in self._items:
            self.add_row(
                self._source_tag(item.source_kind),
                trajectories.get(item.source_uid, "🆕"),
                self._truncate(self._display_title(item)),
                self._relative(item.published_at, now),
            )
        if self._items:
            self.move_cursor(row=0, column=0)

    def _display_title(self, item: FeedItem) -> str:
        prefix = "✓ " if item.seen else ""
        sentiment_module = import_module("ai_dashboard.sentiment")
        indicator = sentiment_module.SENTIMENT_INDICATORS.get(item.sentiment, " ")
        return f"{prefix}{indicator} {item.title}"

    def _relative(self, dt: datetime, now: datetime) -> str:
        delta = now - dt
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 60:
            return "now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"

    def _truncate(self, s: str, n: int = 60) -> str:
        if len(s) > n:
            return s[: n - 1] + "…"
        return s

    def _source_tag(self, kind: str) -> str:
        tag = (
            CATALOG_BY_KIND[kind].tab_label
            if kind in CATALOG_BY_KIND
            else kind[:2].upper()
        )
        return tag

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(self._items):
            now = time.monotonic()
            if self._current_item is not None:
                dwell = now - self._highlight_time
                if dwell >= 2.0:
                    self.post_message(self.ItemViewed(self._current_item))
                else:
                    self.post_message(self.ItemSkipped(self._current_item))

            self._current_item = self._items[event.cursor_row]
            self._highlight_time = now
            self.post_message(self.ItemSelected(self._current_item))

    def action_toggle_read(self) -> None:
        row_idx = self.cursor_row
        if 0 <= row_idx < len(self._items):
            self.post_message(self.ToggleRead(self._items[row_idx]))
