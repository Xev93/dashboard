from __future__ import annotations

from typing import Any, Protocol

import httpx

from ai_dashboard.storage.models import FeedItem


class SourceAdapter(Protocol):
    kind: str
    default_interval_seconds: int

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None: ...

    async def fetch(self) -> list[FeedItem]: ...


class SourceError(Exception):
    pass


class SourceRateLimited(SourceError):
    pass
