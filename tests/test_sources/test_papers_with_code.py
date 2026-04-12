from __future__ import annotations

from importlib import import_module
from datetime import timezone

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter


PWC_URL = "https://paperswithcode.com/api/v1/papers/"
PWC_PAYLOAD = {
    "count": 1,
    "results": [
        {
            "id": "test-paper",
            "title": "Test Paper",
            "url_abs": "https://arxiv.org/abs/1234",
            "published": "2024-01-01",
            "abstract": "Test abstract",
        }
    ],
}


def build_adapter(client: httpx.AsyncClient) -> SourceAdapter:
    adapter_class = import_module(
        "ai_dashboard.sources.papers_with_code"
    ).PapersWithCodeAdapter
    return adapter_class(http=client, options={})


@pytest.mark.asyncio
async def test_pwc_parses_papers() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                PWC_URL, params={"ordering": "-published", "items_per_page": 25}
            ).respond(
                status_code=200,
                json=PWC_PAYLOAD,
            )

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "papers_with_code"
    assert item.source_uid == "pwc_test-paper"
    assert item.title == "Test Paper"
    assert item.url == "https://arxiv.org/abs/1234"
    assert item.published_at.isoformat() == "2024-01-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "abstract": "Test abstract",
        "paper_id": "test-paper",
    }


def test_pwc_source_kind() -> None:
    adapter_class = import_module(
        "ai_dashboard.sources.papers_with_code"
    ).PapersWithCodeAdapter
    assert adapter_class.source_kind == "papers_with_code"


@pytest.mark.asyncio
async def test_pwc_handles_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                PWC_URL, params={"ordering": "-published", "items_per_page": 25}
            ).respond(
                status_code=500,
                json={"detail": "server error"},
            )

            items = await adapter.fetch()

    assert items == []
