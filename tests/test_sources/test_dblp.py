from __future__ import annotations

from datetime import timezone
from importlib import import_module
from typing import cast

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter


DBLP_URL = "https://dblp.org/search/publ/api"
DBLP_PAYLOAD = {
    "result": {
        "hits": {
            "@total": "1",
            "hit": [
                {
                    "info": {
                        "title": "Test Paper",
                        "authors": {"author": {"text": "Author"}},
                        "venue": "NeurIPS",
                        "year": "2025",
                        "key": "conf/nips/Test25",
                        "ee": "https://example.com",
                    }
                }
            ],
        }
    }
}


def build_adapter(client: httpx.AsyncClient) -> SourceAdapter:
    adapter_class = import_module("ai_dashboard.sources.dblp").DblpAdapter
    return cast(
        SourceAdapter,
        adapter_class(http=client, options={"venues": ["NeurIPS"], "year": 2025}),
    )


@pytest.mark.asyncio
async def test_dblp_parses_hits() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                DBLP_URL,
                params={"q": "venue:NeurIPS", "h": 25, "format": "json"},
            ).respond(status_code=200, json=DBLP_PAYLOAD)

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "dblp"
    assert item.source_uid == "dblp_conf/nips/Test25"
    assert item.title == "Test Paper"
    assert item.url == "https://example.com"
    assert item.published_at.isoformat() == "2025-07-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "venue": "NeurIPS",
        "authors": ["Author"],
        "doi": "",
        "dblp_key": "conf/nips/Test25",
    }


def test_dblp_source_kind() -> None:
    adapter_class = import_module("ai_dashboard.sources.dblp").DblpAdapter
    assert adapter_class.source_kind == "dblp"


@pytest.mark.asyncio
async def test_dblp_handles_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                DBLP_URL,
                params={"q": "venue:NeurIPS", "h": 25, "format": "json"},
            ).respond(status_code=500, json={"detail": "server error"})

            items = await adapter.fetch()

    assert items == []
