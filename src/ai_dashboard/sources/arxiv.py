from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, ClassVar, cast

import feedparser
import httpx

from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem


class ArxivAdapter:
    kind = "arxiv"
    default_interval_seconds = 600
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _last_request_time: ClassVar[float] = 0.0
    _endpoint: ClassVar[str] = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.AI+OR+cat:cs.CV&"
        "sortBy=submittedDate&sortOrder=descending&max_results=50"
    )

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self.http = http
        self.options = options

    @classmethod
    def reset_rate_limiter(cls) -> None:
        cls._last_request_time = 0.0

    async def fetch(self) -> list[FeedItem]:
        try:
            async with ArxivAdapter._lock:
                wait_seconds = max(
                    0.0,
                    3.0 - (time.monotonic() - ArxivAdapter._last_request_time),
                )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                ArxivAdapter._last_request_time = time.monotonic()

            response = await self.http.get(ArxivAdapter._endpoint)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise SourceRateLimited(f"arxiv rate limited: {e}") from e
            raise SourceError(f"arxiv http {e.response.status_code}: {e}") from e
        except httpx.HTTPError as e:
            raise SourceError(f"arxiv fetch failed: {e}") from e

        parsed = feedparser.parse(response.content)
        items: list[FeedItem] = []
        now = datetime.now(timezone.utc)

        for raw_entry in parsed.entries:
            entry = cast(Any, raw_entry)
            source_uid = entry.id.rsplit("/", 1)[-1]
            published_struct = cast(
                tuple[int, int, int, int, int, int] | None,
                entry.get("published_parsed") or entry.get("updated_parsed"),
            )
            published_at = (
                datetime(*published_struct[:6], tzinfo=timezone.utc)
                if published_struct
                else now
            )
            primary_category = (
                entry.get("arxiv_primary_category", {}).get("term")
                if entry.get("arxiv_primary_category")
                else (entry.tags[0].term if entry.get("tags") else "")
            )
            items.append(
                FeedItem(
                    id=None,
                    source_kind="arxiv",
                    source_uid=source_uid,
                    title=(entry.title or "").strip().replace("\n", " "),
                    url=entry.link or entry.id,
                    published_at=published_at,
                    raw_payload={
                        "authors": [
                            a.get("name", "") for a in entry.get("authors", [])
                        ],
                        "abstract": (entry.get("summary") or "").strip(),
                        "arxiv_id": source_uid,
                        "primary_category": primary_category,
                    },
                    seen=False,
                    created_at=now,
                )
            )

        return items
