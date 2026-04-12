from __future__ import annotations

from datetime import datetime

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class ChronologicalAllSourcesStrategy:
    name = "chronological-all"

    def __init__(self, limit: int = 500) -> None:
        self.limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        return await db.get_items(limit=self.limit)
