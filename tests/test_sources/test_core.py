from __future__ import annotations

from datetime import timezone
from importlib import import_module
from typing import cast

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter


CORE_URL = "https://api.core.ac.uk/v3/search/works"
CORE_PAYLOAD = {
    "results": [
        {
            "id": 123,
            "title": "Test Paper",
            "abstract": "Test abstract",
            "publishedDate": "2025-01-01",
            "downloadUrl": "https://example.com/paper.pdf",
            "authors": [{"name": "Author One"}],
            "doi": "10.1234/test",
            "citationCount": 5,
        }
    ]
}


def build_adapter(
    client: httpx.AsyncClient, options: dict[str, object] | None = None
) -> SourceAdapter:
    adapter_class = import_module("ai_dashboard.sources.core").CoreAdapter
    resolved_options = (
        options
        if options is not None
        else {
            "api_key": "test-key",
            "query": "artificial intelligence machine learning",
        }
    )
    return cast(
        SourceAdapter,
        adapter_class(
            http=client,
            options=resolved_options,
        ),
    )


@pytest.mark.asyncio
async def test_core_parses_results() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                CORE_URL,
                params={"q": "artificial intelligence machine learning", "limit": 25},
                headers={"Authorization": "Bearer test-key"},
            ).respond(status_code=200, json=CORE_PAYLOAD)

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "core"
    assert item.source_uid == "core_123"
    assert item.title == "Test Paper"
    assert item.url == "https://example.com/paper.pdf"
    assert item.published_at.isoformat() == "2025-01-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "abstract": "Test abstract",
        "authors": ["Author One"],
        "doi": "10.1234/test",
        "citation_count": 5,
    }


def test_core_source_kind() -> None:
    adapter_class = import_module("ai_dashboard.sources.core").CoreAdapter
    assert adapter_class.source_kind == "core"


@pytest.mark.asyncio
async def test_core_handles_401(caplog: pytest.LogCaptureFixture) -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                CORE_URL,
                params={"q": "artificial intelligence machine learning", "limit": 25},
                headers={"Authorization": "Bearer test-key"},
            ).respond(status_code=401, json={"error": "unauthorized"})

            items = await adapter.fetch()

    assert items == []
    assert "invalid or unauthorized" in caplog.text
    assert "test-key" not in caplog.text


@pytest.mark.asyncio
async def test_core_missing_api_key(caplog: pytest.LogCaptureFixture) -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client, options={})

        items = await adapter.fetch()

    assert items == []
    assert "API key missing" in caplog.text
