from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import ClassVar

import httpx

from ..storage.models import FeedItem

DEFAULT_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://research.facebook.com/feed/",
]

logger = logging.getLogger(__name__)


class LabBlogAdapter:
    kind: ClassVar[str] = "lab_blog"
    source_kind: ClassVar[str] = "lab_blog"
    default_interval_seconds: ClassVar[int] = 3600

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        self._feeds: list[str] = _resolve_feeds(options)

    async def fetch(self) -> list[FeedItem]:
        results = await asyncio.gather(
            *(self._fetch_feed(feed_url) for feed_url in self._feeds),
            return_exceptions=True,
        )

        items: list[FeedItem] = []
        for feed_url, result in zip(self._feeds, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning("[lab_blog] failed %s: %s", feed_url, result)
                continue
            items.extend(result)
        return items

    async def _fetch_feed(self, feed_url: str) -> list[FeedItem]:
        try:
            response = await self._http.get(feed_url)
            _ = response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("[lab_blog] failed %s: %s", feed_url, exc)
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            logger.warning("[lab_blog] skipped malformed feed %s: %s", feed_url, exc)
            return []

        now = datetime.now(timezone.utc)
        items: list[FeedItem] = []

        for item in root.findall(".//item"):
            title = _clean_text(item.findtext("title"))
            link = _clean_text(item.findtext("link"))
            if not link:
                logger.warning("[lab_blog] skipped item without link from %s", feed_url)
                continue

            published_at = _parse_published_at(item.findtext("pubDate"), default=now)
            description = _clean_text(item.findtext("description"))

            items.append(
                FeedItem(
                    id=None,
                    source_kind=self.source_kind,
                    source_uid=link,
                    title=title,
                    url=link,
                    published_at=published_at,
                    raw_payload={
                        "feed_url": feed_url,
                        "description": description,
                    },
                    seen=False,
                    created_at=now,
                )
            )

        return items


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _resolve_feeds(options: dict[str, object]) -> list[str]:
    feeds = options.get("feeds")
    if feeds is None:
        return list(DEFAULT_FEEDS)
    if isinstance(feeds, Sequence) and not isinstance(feeds, (str, bytes)):
        return [feed for feed in feeds if isinstance(feed, str)]
    return list(DEFAULT_FEEDS)


def _parse_published_at(value: str | None, default: datetime) -> datetime:
    if not value:
        return default

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None

    if parsed is None:
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning("[lab_blog] could not parse pubDate %r", value)
            return default

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
