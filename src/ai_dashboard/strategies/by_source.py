from __future__ import annotations

from datetime import datetime

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class BySourceStrategy:
    """Filter items to a single source_kind."""

    name: str
    _source_kind: str
    _limit: int

    def __init__(self, source_kind: str, limit: int = 500) -> None:
        self.name = f"by-source-{source_kind}"
        self._source_kind = source_kind
        self._limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        _ = now
        try:
            return await db.get_items(limit=self._limit, source_kind=self._source_kind)
        except TypeError:
            all_items = await db.get_items(limit=self._limit)
            return [item for item in all_items if item.source_kind == self._source_kind]
