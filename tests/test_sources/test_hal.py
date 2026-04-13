from __future__ import annotations

from datetime import timezone
from importlib import import_module
from typing import cast

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter, SourceError


HAL_URL = "https://api.archives-ouvertes.fr/search/"
HAL_PAYLOAD = {
    "response": {
        "docs": [
            {
                "halId_s": "hal-001",
                "title_s": ["Test Paper"],
                "uri_s": "https://hal.archives-ouvertes.fr/hal-001",
                "abstract_s": ["Abstract"],
                "modifiedDate_tdate": "2025-01-01T00:00:00Z",
                "authFullName_s": ["Author One"],
            }
        ]
    }
}


def build_adapter(client: httpx.AsyncClient) -> SourceAdapter:
    adapter_class = import_module("ai_dashboard.sources.hal").HalAdapter
    return cast(
        SourceAdapter,
        adapter_class(
            http=client,
            options={
                "query": "artificial intelligence OR machine learning",
                "domain": "info",
            },
        ),
    )


@pytest.mark.asyncio
async def test_hal_parses_docs() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                HAL_URL,
                params={
                    "q": "artificial intelligence OR machine learning",
                    "fq": "domainAllCode_s:info*",
                    "rows": 25,
                    "sort": "modifiedDate_tdate desc",
                    "wt": "json",
                    "fl": "halId_s,title_s,uri_s,abstract_s,modifiedDate_tdate,authFullName_s",
                },
            ).respond(status_code=200, json=HAL_PAYLOAD)

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "hal"
    assert item.source_uid == "hal_hal-001"
    assert item.title == "Test Paper"
    assert item.url == "https://hal.archives-ouvertes.fr/hal-001"
    assert item.published_at.isoformat() == "2025-01-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "abstract": "Abstract",
        "authors": ["Author One"],
        "domain": "info",
    }


def test_hal_source_kind() -> None:
    adapter_class = import_module("ai_dashboard.sources.hal").HalAdapter
    assert adapter_class.source_kind == "hal"


@pytest.mark.asyncio
async def test_hal_handles_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                HAL_URL,
                params={
                    "q": "artificial intelligence OR machine learning",
                    "fq": "domainAllCode_s:info*",
                    "rows": 25,
                    "sort": "modifiedDate_tdate desc",
                    "wt": "json",
                    "fl": "halId_s,title_s,uri_s,abstract_s,modifiedDate_tdate,authFullName_s",
                },
            ).respond(status_code=500, json={"detail": "server error"})

            with pytest.raises(SourceError):
                _ = await adapter.fetch()
