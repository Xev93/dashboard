from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem


class HuggingFaceAdapter:
    kind = "huggingface"
    default_interval_seconds = 600

    _endpoints: dict[str, str] = {
        "model": "https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=30",
        "dataset": "https://huggingface.co/api/datasets?sort=createdAt&direction=-1&limit=20",
        "space": "https://huggingface.co/api/spaces?sort=createdAt&direction=-1&limit=20",
    }

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self.http = http
        self.options = options

    async def fetch(self) -> list[FeedItem]:
        models, datasets, spaces = await asyncio.gather(
            self._fetch_json("model", self._endpoints["model"]),
            self._fetch_json("dataset", self._endpoints["dataset"]),
            self._fetch_json("space", self._endpoints["space"]),
        )
        items: list[FeedItem] = []
        items.extend(self._build_items("model", models))
        items.extend(self._build_items("dataset", datasets))
        items.extend(self._build_items("space", spaces))
        return items

    async def _fetch_json(self, kind_prefix: str, url: str) -> list[dict[str, Any]]:
        try:
            response = await self.http.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise SourceRateLimited(f"{kind_prefix} rate limited: {e}") from e
            raise SourceError(
                f"{kind_prefix} http {e.response.status_code}: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise SourceError(f"{kind_prefix} fetch failed: {e}") from e

        data = response.json()
        return data if isinstance(data, list) else []

    def _build_items(
        self, kind_prefix: str, payload: list[dict[str, Any]]
    ) -> list[FeedItem]:
        now = datetime.now(timezone.utc)
        return [self._build_item(kind_prefix, item, now) for item in payload]

    def _build_item(
        self,
        kind_prefix: str,
        item: dict[str, Any],
        now: datetime,
    ) -> FeedItem:
        item_id = item["id"]
        return FeedItem(
            id=None,
            source_kind="huggingface",
            source_uid=f"{kind_prefix}:{item_id}",
            title=f"{kind_prefix}: {item_id}",
            url=self._build_url(kind_prefix, item_id),
            published_at=self._parse_datetime(
                item.get("createdAt") or item.get("lastModified"),
                now,
            ),
            raw_payload={
                "hf_kind": kind_prefix,
                "id": item_id,
                "author": item.get("author"),
                "pipeline_tag": item.get("pipeline_tag"),
                "downloads": item.get("downloads"),
                "likes": item.get("likes"),
                "tags": item.get("tags"),
                "lastModified": item.get("lastModified"),
            },
            seen=False,
            created_at=now,
        )

    def _build_url(self, kind_prefix: str, item_id: str) -> str:
        if kind_prefix == "model":
            return f"https://huggingface.co/{item_id}"
        if kind_prefix == "dataset":
            return f"https://huggingface.co/datasets/{item_id}"
        return f"https://huggingface.co/spaces/{item_id}"

    def _parse_datetime(self, value: Any, fallback: datetime) -> datetime:
        if not value or not isinstance(value, str):
            return fallback
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
