from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import ClassVar, cast

import httpx

from ai_dashboard.sources.base import SourceError
from ai_dashboard.storage.models import FeedItem


logger = logging.getLogger(__name__)


class CoreAdapter:
    kind: ClassVar[str] = "core"
    source_kind: ClassVar[str] = "core"
    default_interval_seconds: ClassVar[int] = 900
    _endpoint: ClassVar[str] = "https://api.core.ac.uk/v3/search/works"
    _default_query: ClassVar[str] = "artificial intelligence machine learning"

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        self._api_key: str = str(options.get("api_key") or "").strip()
        self._query: str = str(options.get("query") or self._default_query)

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []
        if not self._api_key:
            logger.warning("CORE API key missing; skipping fetch")
            return items

        try:
            response = await self._http.get(
                self._endpoint,
                params={"q": self._query, "limit": 25, "sort": "createdDate:desc"},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            if response.status_code == 429:
                logger.warning("CORE rate limited for query %r", self._query)
                return items
            if response.status_code in {401, 403}:
                logger.error("CORE API key invalid or unauthorized")
                return items
            _ = response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "CORE request failed with status %s for query %r",
                exc.response.status_code,
                self._query,
            )
            raise SourceError(f"CORE http {exc.response.status_code}: {exc}") from exc
        except httpx.HTTPError as exc:
            logger.warning("CORE fetch failed for query %r: %s", self._query, exc)
            raise SourceError(f"CORE fetch failed: {exc}") from exc

        payload_obj = cast(object, response.json())
        if not isinstance(payload_obj, dict):
            logger.warning("CORE returned unexpected payload type")
            return items

        payload = cast(dict[str, object], payload_obj)
        results_obj = payload.get("results", [])
        if not isinstance(results_obj, list):
            logger.warning("CORE returned unexpected payload shape")
            return items

        for result_obj in cast(list[object], results_obj):
            if not isinstance(result_obj, dict):
                continue
            result = cast(dict[str, object], result_obj)
            try:
                items.append(self._build_feed_item(result))
            except Exception as exc:
                logger.warning("Skipping CORE work %r: %s", result.get("id"), exc)

        return items

    def _build_feed_item(self, result: dict[str, object]) -> FeedItem:
        result_id = str(result.get("id") or "").strip()
        if not result_id:
            raise ValueError("missing id")

        title = str(result.get("title") or "").strip()
        authors = self._authors(result.get("authors"))

        return FeedItem(
            id=None,
            source_kind=self.source_kind,
            source_uid=f"core_{result_id}",
            title=title,
            url=self._work_url(result_id, result.get("downloadUrl")),
            published_at=self._published_at(
                result.get("createdDate") or result.get("publishedDate")
            ),
            raw_payload={
                "abstract": str(result.get("abstract") or "")[:500],
                "authors": authors,
                "doi": str(result.get("doi") or ""),
                "citation_count": self._citation_count(result.get("citationCount")),
                "download_url": str(result.get("downloadUrl") or ""),
            },
        )

    def _authors(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []

        authors: list[str] = []
        for author_obj in cast(list[object], value):
            if not isinstance(author_obj, dict):
                continue
            author = cast(dict[str, object], author_obj)
            name = str(author.get("name") or "").strip()
            if name:
                authors.append(name)
        return authors

    def _citation_count(self, value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return int(value)
            except ValueError:
                logger.warning("Invalid CORE citationCount %r", value)
        return 0

    def _work_url(self, result_id: str, download_url: object) -> str:
        value = str(download_url or "").strip()
        if value:
            return value
        return f"https://core.ac.uk/works/{result_id}"

    def _published_at(self, value: object) -> datetime:
        date_text = str(value or "").strip()
        if date_text:
            normalized = (
                date_text[:-1] + "+00:00" if date_text.endswith("Z") else date_text
            )
            try:
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                logger.warning("Invalid CORE publishedDate %r", date_text)

        return datetime.now(timezone.utc)
