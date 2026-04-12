from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ai_dashboard.sources.arxiv import ArxivAdapter
from ai_dashboard.sources.base import SourceError, SourceRateLimited


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "arxiv_response.xml"
ARXIV_URL = (
    "https://export.arxiv.org/api/query?"
    "search_query=cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.AI+OR+cat:cs.CV&"
    "sortBy=submittedDate&sortOrder=descending&max_results=50"
)


@pytest.mark.asyncio
async def test_arxiv_fetch_parses_fixture() -> None:
    fixture = FIXTURE_PATH.read_text()
    with respx.mock() as mock:
        mock.get(ARXIV_URL).respond(status_code=200, text=fixture)
        async with httpx.AsyncClient() as client:
            ArxivAdapter.reset_rate_limiter()
            result = await ArxivAdapter(http=client, options={}).fetch()

    assert len(result) == 2
    assert result[0].source_kind == "arxiv"
    assert result[0].source_uid.startswith("2604.")
    assert "Transformer" in result[0].title


@pytest.mark.asyncio
async def test_arxiv_raw_payload_fields() -> None:
    fixture = FIXTURE_PATH.read_text()
    with respx.mock() as mock:
        mock.get(ARXIV_URL).respond(status_code=200, text=fixture)
        async with httpx.AsyncClient() as client:
            ArxivAdapter.reset_rate_limiter()
            result = await ArxivAdapter(http=client, options={}).fetch()

    assert set(result[0].raw_payload) >= {
        "authors",
        "abstract",
        "arxiv_id",
        "primary_category",
    }
    assert len(result[0].raw_payload["authors"]) == 2
    assert result[0].raw_payload["primary_category"] == "cs.LG"


@pytest.mark.asyncio
async def test_arxiv_http_error_raises_source_error() -> None:
    with respx.mock() as mock:
        mock.get(ARXIV_URL).respond(status_code=500)
        async with httpx.AsyncClient() as client:
            ArxivAdapter.reset_rate_limiter()
            with pytest.raises(SourceError):
                await ArxivAdapter(http=client, options={}).fetch()


@pytest.mark.asyncio
async def test_arxiv_429_raises_rate_limited() -> None:
    with respx.mock() as mock:
        mock.get(ARXIV_URL).respond(status_code=429)
        async with httpx.AsyncClient() as client:
            ArxivAdapter.reset_rate_limiter()
            with pytest.raises(SourceRateLimited):
                await ArxivAdapter(http=client, options={}).fetch()
