from __future__ import annotations

from typing import Any

import httpx

from ai_dashboard.storage.models import FeedItem


class NullAdapter:
    kind = "null"
    default_interval_seconds = 3600

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._http = http
        self._options = options or {}

    async def fetch(self) -> list[FeedItem]:
        return []
