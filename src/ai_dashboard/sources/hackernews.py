from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ai_dashboard.config import DEFAULT_HN_KEYWORDS
from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem


logger = logging.getLogger(__name__)


class HackerNewsAdapter:
    kind = "hn"
    default_interval_seconds = 120

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self._http = http
        self._keywords = list(options.get("keywords", DEFAULT_HN_KEYWORDS))
        self._pattern = re.compile(
            r"\b("
            + "|".join(re.escape(keyword) for keyword in self._keywords)
            + r")\b",
            re.IGNORECASE,
        )

    async def fetch(self) -> list[FeedItem]:
        try:
            response = await self._http.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )
            if response.status_code == 429:
                raise SourceRateLimited("Hacker News topstories rate limited")
            response.raise_for_status()
            story_ids = response.json()
            semaphore = asyncio.Semaphore(10)
            results = await asyncio.gather(
                *[
                    self._fetch_story(story_id=story_id, semaphore=semaphore)
                    for story_id in story_ids[:30]
                ],
                return_exceptions=True,
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"Failed to fetch Hacker News stories: {exc}") from exc

        items: list[FeedItem] = []
        for story_id, result in zip(story_ids[:30], results, strict=False):
            if isinstance(result, Exception):
                logger.warning(f"[hn] failed to fetch story {story_id}: {result}")
                continue
            if not result:
                continue
            if not self._matches(result):
                continue
            items.append(self._build_feed_item(result))
        return items

    async def _fetch_story(
        self, story_id: int, semaphore: asyncio.Semaphore
    ) -> dict[str, Any] | None:
        async with semaphore:
            response = await self._http.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            )
            if response.status_code == 429:
                raise SourceRateLimited(f"Hacker News story {story_id} rate limited")
            response.raise_for_status()
            item = response.json()
        if not isinstance(item, dict):
            return None
        if item.get("type") != "story":
            return None
        return item

    def _matches(self, item: dict[str, Any]) -> bool:
        text = f"{item.get('title', '')} {item.get('url', '')}"
        return self._pattern.search(text) is not None

    def _build_feed_item(self, item: dict[str, Any]) -> FeedItem:
        story_id = item.get("id", 0)
        return FeedItem(
            id=None,
            source_kind="hn",
            source_uid=str(story_id),
            title=item.get("title", ""),
            url=item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
            published_at=datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc),
            raw_payload={
                "points": item.get("score"),
                "comment_count": item.get("descendants"),
                "submitted_by": item.get("by"),
                "hn_id": story_id,
                "text": item.get("text"),
            },
        )
