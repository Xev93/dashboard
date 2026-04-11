from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class FeedListStrategy(Protocol):
    name: str

    async def items(self, db: Database, now: datetime) -> list[FeedItem]: ...
