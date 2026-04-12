from __future__ import annotations

from datetime import datetime
from typing import cast

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy


class FilteredStrategy:
    """Decorator that filters another strategy's items by text match."""

    name: str
    _base: FeedListStrategy
    _text: str

    def __init__(self, base: FeedListStrategy, text: str) -> None:
        self.name = f"filtered-{getattr(base, 'name', 'strategy')}"
        self._base = base
        self._text = text.lower()

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        all_items = await self._base.items(db, now)
        return [item for item in all_items if self._matches(item)]

    def _matches(self, item: FeedItem) -> bool:
        if self._text in (item.title or "").lower():
            return True
        if self._text in (item.url or "").lower():
            return True
        if item.raw_payload:
            for val in cast(dict[str, object], item.raw_payload).values():
                if isinstance(val, str) and self._text in val.lower():
                    return True
        return False
