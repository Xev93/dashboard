from __future__ import annotations

from datetime import timezone
from importlib import import_module
from typing import cast

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter


S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAYLOAD = {
    "total": 1,
    "data": [
        {
            "paperId": "abc123",
            "title": "Test",
            "url": "https://example.com",
            "abstract": "Test abstract",
            "year": 2025,
            "citationCount": 10,
            "publicationDate": "2025-01-01",
            "externalIds": {"DOI": "10.1234/test"},
        }
    ],
}


def build_adapter(client: httpx.AsyncClient) -> SourceAdapter:
    adapter_class = import_module(
        "ai_dashboard.sources.semantic_scholar"
    ).SemanticScholarAdapter
    return cast(
        SourceAdapter,
        adapter_class(
            http=client,
            options={"query": "artificial intelligence machine learning"},
        ),
    )


@pytest.mark.asyncio
async def test_s2_parses_papers() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                S2_URL,
                params={
                    "query": "artificial intelligence machine learning",
                    "limit": 25,
                    "fields": "title,url,abstract,year,citationCount,publicationDate,externalIds",
                },
            ).respond(status_code=200, json=S2_PAYLOAD)

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "semantic_scholar"
    assert item.source_uid == "s2_abc123"
    assert item.title == "Test"
    assert item.url == "https://example.com"
    assert item.published_at.isoformat() == "2025-01-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "abstract": "Test abstract",
        "citation_count": 10,
        "year": 2025,
        "doi": "10.1234/test",
    }


def test_s2_source_kind() -> None:
    adapter_class = import_module(
        "ai_dashboard.sources.semantic_scholar"
    ).SemanticScholarAdapter
    assert adapter_class.source_kind == "semantic_scholar"


@pytest.mark.asyncio
async def test_s2_handles_429() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                S2_URL,
                params={
                    "query": "artificial intelligence machine learning",
                    "limit": 25,
                    "fields": "title,url,abstract,year,citationCount,publicationDate,externalIds",
                },
            ).respond(status_code=429, json={"error": "rate limited"})

            items = await adapter.fetch()

    assert items == []
