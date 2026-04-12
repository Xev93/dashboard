from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from ai_dashboard.config import DEFAULT_NEWSLETTER_FEEDS
from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem


class NewsletterAdapter:
    kind = "newsletter"
    default_interval_seconds = 3600

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self._http = http
        self._feeds = list(options.get("feeds", DEFAULT_NEWSLETTER_FEEDS))

    async def fetch(self) -> list[FeedItem]:
        results = await asyncio.gather(
            *(self._fetch_feed(feed_url) for feed_url in self._feeds),
            return_exceptions=True,
        )

        items: list[FeedItem] = []
        failed_feeds = 0

        for feed_url, result in zip(self._feeds, results, strict=False):
            if isinstance(result, Exception):
                failed_feeds += 1
                print(f"[newsletter] failed {feed_url}: {result}", file=sys.stderr)
                continue
            if result is None:
                failed_feeds += 1
                continue
            items.extend(result)

        if self._feeds and failed_feeds == len(self._feeds):
            raise SourceError("all newsletter feeds failed")

        return items

    async def _fetch_feed(self, feed_url: str) -> list[FeedItem] | None:
        try:
            response = await self._http.get(feed_url)
            if response.status_code == 429:
                raise SourceRateLimited(f"newsletter feed rate limited: {feed_url}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"[newsletter] failed {feed_url}: {exc}", file=sys.stderr)
            return None

        parsed_feed = feedparser.parse(response.content)
        if parsed_feed.bozo and not parsed_feed.entries:
            print(
                f"[newsletter] skipped malformed feed {feed_url}: {parsed_feed.bozo_exception}",
                file=sys.stderr,
            )
            return None

        publication_name = parsed_feed.feed.get("title") or urlparse(feed_url).netloc
        feed_url_hash = hashlib.md5(feed_url.encode()).hexdigest()[:8]
        now = datetime.now(timezone.utc)

        items: list[FeedItem] = []
        for entry in parsed_feed.entries:
            published_struct = entry.get("published_parsed") or entry.get(
                "updated_parsed"
            )
            published_at = (
                datetime(*published_struct[:6], tzinfo=timezone.utc)
                if published_struct
                else now
            )
            entry_uid = (
                entry.get("id")
                or entry.get("guid")
                or entry.get("link")
                or entry.get("title", "")
            )
            title = (entry.get("title") or "").strip()
            url = entry.get("link") or ""
            summary_text = entry.get("summary") or entry.get("description") or ""
            items.append(
                FeedItem(
                    id=None,
                    source_kind="newsletter",
                    source_uid=f"{feed_url_hash}:{entry_uid}",
                    title=title,
                    url=url,
                    published_at=published_at,
                    raw_payload={
                        "publication": publication_name,
                        "summary": summary_text,
                        "pub_date": published_at.isoformat(),
                        "feed_url": feed_url,
                    },
                    seen=False,
                    created_at=now,
                )
            )

        return items
