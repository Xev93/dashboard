from __future__ import annotations

from datetime import timezone
from importlib import import_module
from typing import cast

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceAdapter


OPENREVIEW_URL = "https://api2.openreview.net/notes"
OPENREVIEW_PAYLOAD = {
    "notes": [
        {
            "id": "abc123",
            "cdate": 1704067200000,
            "content": {
                "title": {"value": "Test Paper"},
                "abstract": {"value": "Test abstract"},
                "authors": {"value": ["Author One"]},
                "venue": {"value": "NeurIPS 2025"},
            },
        }
    ]
}


def build_adapter(client: httpx.AsyncClient) -> SourceAdapter:
    adapter_class = import_module("ai_dashboard.sources.openreview").OpenReviewAdapter
    return cast(
        SourceAdapter,
        adapter_class(
            http=client,
            options={"venues": ["NeurIPS.cc/2025/Conference"]},
        ),
    )


@pytest.mark.asyncio
async def test_or_parses_notes() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                OPENREVIEW_URL,
                params={
                    "invitation": "NeurIPS.cc/2025/Conference/-/Submission",
                    "limit": 25,
                    "sort": "cdate:desc",
                },
            ).respond(status_code=200, json=OPENREVIEW_PAYLOAD)

            items = await adapter.fetch()

    assert len(items) == 1
    item = items[0]
    assert item.source_kind == "openreview"
    assert item.source_uid == "or_abc123"
    assert item.title == "Test Paper"
    assert item.url == "https://openreview.net/forum?id=abc123"
    assert item.published_at.isoformat() == "2024-01-01T00:00:00+00:00"
    assert item.published_at.tzinfo == timezone.utc
    assert item.raw_payload == {
        "abstract": "Test abstract",
        "venue": "NeurIPS.cc/2025/Conference",
        "authors": ["Author One"],
    }


def test_or_source_kind() -> None:
    adapter_class = import_module("ai_dashboard.sources.openreview").OpenReviewAdapter
    assert adapter_class.source_kind == "openreview"


@pytest.mark.asyncio
async def test_or_handles_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = build_adapter(client)

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(
                OPENREVIEW_URL,
                params={
                    "invitation": "NeurIPS.cc/2025/Conference/-/Submission",
                    "limit": 25,
                    "sort": "cdate:desc",
                },
            ).respond(status_code=500, json={"detail": "server error"})

            items = await adapter.fetch()

    assert items == []
