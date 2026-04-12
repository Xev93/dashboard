from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import ClassVar, TypedDict, cast

import httpx

from ai_dashboard.storage.models import FeedItem


logger = logging.getLogger(__name__)


class PaperPayload(TypedDict, total=False):
    id: str
    title: str
    url_abs: str
    published: str
    abstract: str


class PapersResponse(TypedDict, total=False):
    results: list[PaperPayload]


class PapersWithCodeAdapter:
    source_kind: ClassVar[str] = "papers_with_code"
    kind: ClassVar[str] = source_kind
    default_interval_seconds: ClassVar[int] = 600
    _endpoint: ClassVar[str] = "https://paperswithcode.com/api/v1/papers/"
    http: httpx.AsyncClient
    options: dict[str, object]

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self.http = http
        self.options = options

    async def fetch(self) -> list[FeedItem]:
        try:
            response = await self.http.get(
                self._endpoint,
                params={"ordering": "-published", "items_per_page": 25},
                headers={"Accept": "application/json"},
            )
            _ = response.raise_for_status()
            payload: object = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Failed to fetch Papers With Code papers: %s", exc)
            return []

        if not isinstance(payload, dict):
            return []
        results = cast(PapersResponse, cast(object, payload)).get("results", [])

        now = datetime.now(timezone.utc)
        items: list[FeedItem] = []
        for paper in results:
            paper_id = paper.get("id")
            title = paper.get("title")
            if not isinstance(paper_id, str) or not isinstance(title, str):
                continue
            url = paper.get("url_abs")

            items.append(
                FeedItem(
                    id=None,
                    source_kind=self.source_kind,
                    source_uid=f"pwc_{paper_id}",
                    title=title,
                    url=url
                    if isinstance(url, str) and url
                    else f"https://paperswithcode.com/paper/{paper_id}",
                    published_at=self._parse_datetime(paper.get("published"), now),
                    raw_payload={
                        "abstract": str(paper.get("abstract", ""))[:500],
                        "paper_id": paper_id,
                    },
                    seen=False,
                    created_at=now,
                )
            )
        return items

    def _parse_datetime(self, value: object, fallback: datetime) -> datetime:
        if not isinstance(value, str) or not value:
            return fallback
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
