from __future__ import annotations

from datetime import datetime, timezone

from textual.message import Message
from textual.widgets import DataTable

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy


class FeedListWidget(DataTable):
    class ItemSelected(Message):
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

    async def on_mount(self) -> None:
        self.add_column("S", key="source")
        self.add_column("Title", key="title")
        self.add_column("Age", key="age")
        await self.refresh_items()

    async def refresh_items(self) -> None:
        now = datetime.now(timezone.utc)
        items = await self.strategy.items(self.db, now)
        self._items = list(items)
        self.clear()
        for item in self._items:
            self.add_row(
                self._source_tag(item.source_kind),
                self._truncate(item.title),
                self._relative(item.published_at, now),
            )
        if self._items:
            self.move_cursor(row=0, column=0)

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
        return {
            "arxiv": "AX",
            "hn": "HN",
            "github_trending": "GH",
            "huggingface": "HF",
            "newsletter": "NL",
        }.get(kind, kind[:2].upper())

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(self._items):
            self.post_message(self.ItemSelected(self._items[event.cursor_row]))
