from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

import httpx

from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class HalAdapter:
    kind: ClassVar[str] = "hal"
    source_kind: ClassVar[str] = "hal"
    default_interval_seconds: ClassVar[int] = 900
    _endpoint: ClassVar[str] = "https://api.archives-ouvertes.fr/search/"
    _default_query: ClassVar[str] = (
        "artificial intelligence OR machine learning OR deep learning"
    )

    def __init__(self, http: httpx.AsyncClient, options: dict[str, object]) -> None:
        self._http: httpx.AsyncClient = http
        self._query: str = str(options.get("query") or self._default_query)
        self._domain: str = str(options.get("domain") or "info")

    async def fetch(self) -> list[FeedItem]:
        params = {
            "q": self._query,
            "fq": f"domainAllCode_s:{self._domain}*",
            "rows": 25,
            "sort": "producedDate_tdate desc",
            "wt": "json",
            "fl": (
                "halId_s,title_s,uri_s,abstract_s,producedDate_tdate,authFullName_s"
            ),
        }

        try:
            response = await self._http.get(self._endpoint, params=params)
            if response.status_code == 429:
                raise SourceRateLimited("HAL search rate limited")
            _ = response.raise_for_status()
            payload_raw: object = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise SourceRateLimited("HAL search rate limited") from exc
            raise SourceError(f"HAL http {exc.response.status_code}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"Failed to fetch HAL results: {exc}") from exc
        except ValueError as exc:
            raise SourceError(f"Failed to decode HAL response: {exc}") from exc

        if not isinstance(payload_raw, dict):
            return []

        payload = payload_raw
        response_payload = payload.get("response", {})
        if not isinstance(response_payload, dict):
            return []

        docs = response_payload.get("docs", [])
        if not isinstance(docs, list):
            return []

        items: list[FeedItem] = []
        now = datetime.now(timezone.utc)

        for doc in docs:
            if not isinstance(doc, dict):
                continue

            hal_id = self._string_value(doc.get("halId_s"))
            if not hal_id:
                continue

            title = self._first_value(doc.get("title_s"))
            abstract = self._first_value(doc.get("abstract_s"))
            published_at = self._parse_datetime(doc.get("producedDate_tdate"), now)
            authors = self._string_list(doc.get("authFullName_s"))

            items.append(
                FeedItem(
                    id=None,
                    source_kind="hal",
                    source_uid=f"hal_{hal_id}",
                    title=title,
                    url=str(doc.get("uri_s", "") or ""),
                    published_at=published_at,
                    raw_payload={
                        "abstract": abstract[:500],
                        "authors": authors,
                        "domain": self._domain,
                    },
                )
            )

        return items

    @staticmethod
    def _first_value(value: JsonValue) -> str:
        if isinstance(value, list):
            return HalAdapter._string_value(value[0] if value else "")
        return HalAdapter._string_value(value)

    @staticmethod
    def _string_list(value: JsonValue) -> list[str]:
        if not isinstance(value, list):
            return []
        return [HalAdapter._string_value(item) for item in value if item is not None]

    @staticmethod
    def _string_value(value: JsonValue) -> str:
        return value if isinstance(value, str) else ""

    @staticmethod
    def _parse_datetime(value: JsonValue, fallback: datetime) -> datetime:
        if not isinstance(value, str) or not value:
            return fallback

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
