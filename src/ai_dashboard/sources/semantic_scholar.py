from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import ClassVar, cast

import httpx

from ai_dashboard.sources.base import SourceError
from ai_dashboard.storage.models import FeedItem


logger = logging.getLogger(__name__)


class SemanticScholarAdapter:
    kind: ClassVar[str] = "semantic_scholar"
    source_kind: ClassVar[str] = "semantic_scholar"
    default_interval_seconds: ClassVar[int] = 900
    _endpoint: ClassVar[str] = "https://api.semanticscholar.org/graph/v1/paper/search"
    _default_query: ClassVar[str] = "artificial intelligence machine learning"
    _default_fields: ClassVar[str] = (
        "title,url,abstract,year,citationCount,publicationDate,externalIds"
    )

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        self._query: str = str(options.get("query") or self._default_query)
        self._fields: str = str(options.get("fields") or self._default_fields)

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []

        try:
            response = await self._http.get(
                self._endpoint,
                params={
                    "query": self._query,
                    "limit": 25,
                    "fields": self._fields,
                },
                headers={"User-Agent": "ai-dashboard/0.2 (research feed reader)"},
            )
            if response.status_code == 429:
                logger.warning(
                    "Semantic Scholar rate limited for query %r", self._query
                )
                return items
            _ = response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Semantic Scholar request failed with status %s for query %r",
                exc.response.status_code,
                self._query,
            )
            raise SourceError(
                f"Semantic Scholar http {exc.response.status_code}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Semantic Scholar fetch failed for query %r: %s", self._query, exc
            )
            raise SourceError(f"Semantic Scholar fetch failed: {exc}") from exc

        payload_obj = cast(object, response.json())
        if not isinstance(payload_obj, dict):
            logger.warning("Semantic Scholar returned unexpected payload type")
            return items

        payload = cast(dict[str, object], payload_obj)
        papers_obj = payload.get("data", [])
        if not isinstance(papers_obj, list):
            logger.warning("Semantic Scholar returned unexpected payload shape")
            return items

        for paper_obj in cast(list[object], papers_obj):
            if not isinstance(paper_obj, dict):
                continue
            paper = cast(dict[str, object], cast(object, paper_obj))
            try:
                items.append(self._build_feed_item(paper))
            except Exception as exc:
                logger.warning(
                    "Skipping Semantic Scholar paper %r: %s",
                    paper.get("paperId"),
                    exc,
                )

        return items

    def _build_feed_item(self, paper: dict[str, object]) -> FeedItem:
        paper_id = str(paper.get("paperId") or "").strip()
        if not paper_id:
            raise ValueError("missing paperId")

        title = str(paper.get("title") or "").strip()
        external_ids_obj = paper.get("externalIds")
        external_ids = (
            cast(dict[str, object], external_ids_obj)
            if isinstance(external_ids_obj, dict)
            else {}
        )

        return FeedItem(
            id=None,
            source_kind=self.source_kind,
            source_uid=f"s2_{paper_id}",
            title=title,
            url=self._paper_url(paper_id, paper.get("url")),
            published_at=self._published_at(
                paper.get("publicationDate"), paper.get("year")
            ),
            raw_payload={
                "abstract": str(paper.get("abstract") or "")[:500],
                "citation_count": self._citation_count(paper.get("citationCount")),
                "year": paper.get("year"),
                "doi": str(external_ids.get("DOI") or ""),
            },
        )

    def _citation_count(self, value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return int(value)
            except ValueError:
                logger.warning("Invalid Semantic Scholar citationCount %r", value)
        return 0

    def _paper_url(self, paper_id: str, url: object) -> str:
        value = str(url or "").strip()
        if value:
            return value
        return f"https://www.semanticscholar.org/paper/{paper_id}"

    def _published_at(self, publication_date: object, year: object) -> datetime:
        date_text = str(publication_date or "").strip()
        if date_text:
            try:
                return datetime.strptime(date_text, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                logger.warning("Invalid Semantic Scholar publicationDate %r", date_text)

        try:
            if isinstance(year, int):
                return datetime(year, 1, 1, tzinfo=timezone.utc)
            if isinstance(year, str) and year.strip():
                return datetime(int(year), 1, 1, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            logger.warning("Invalid Semantic Scholar year %r", year)

        return datetime.now(timezone.utc)
