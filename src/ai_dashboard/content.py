from __future__ import annotations

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class ContentFetcher:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def fetch_content(self, item: FeedItem) -> str:
        payload = item.raw_payload
        for key in (
            "content",
            "body",
            "readme",
            "text",
            "abstract",
            "summary",
            "description",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return item.url or "(no content available)"
