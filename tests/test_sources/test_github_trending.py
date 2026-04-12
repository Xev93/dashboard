from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceError
from ai_dashboard.sources.github_trending import GithubTrendingAdapter


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "github_trending.html"
TRENDING_URL = "https://github.com/trending?since=daily&spoken_language_code=en"
PYTHON_TRENDING_URL = "https://github.com/trending/python?since=daily"


@pytest.mark.asyncio
async def test_gh_trending_filters_ai_repos() -> None:
    fixture = FIXTURE_PATH.read_text()
    with respx.mock() as mock:
        mock.get(TRENDING_URL).respond(status_code=200, text=fixture)
        mock.get(PYTHON_TRENDING_URL).respond(status_code=200, text=fixture)
        async with httpx.AsyncClient() as client:
            result = await GithubTrendingAdapter(http=client, options={}).fetch()

    assert len(result) == 2
    assert [item.source_uid for item in result] == [
        "openai/example-llm-agents",
        "huggingface/transformers-next",
    ]


@pytest.mark.asyncio
async def test_gh_trending_parses_stars() -> None:
    fixture = FIXTURE_PATH.read_text()
    with respx.mock() as mock:
        mock.get(TRENDING_URL).respond(status_code=200, text=fixture)
        mock.get(PYTHON_TRENDING_URL).respond(status_code=200, text=fixture)
        async with httpx.AsyncClient() as client:
            result = await GithubTrendingAdapter(http=client, options={}).fetch()

    item = next(
        item for item in result if item.source_uid == "openai/example-llm-agents"
    )
    assert item.raw_payload["stars"] == 42351


@pytest.mark.asyncio
async def test_gh_trending_parses_language() -> None:
    fixture = FIXTURE_PATH.read_text()
    with respx.mock() as mock:
        mock.get(TRENDING_URL).respond(status_code=200, text=fixture)
        mock.get(PYTHON_TRENDING_URL).respond(status_code=200, text=fixture)
        async with httpx.AsyncClient() as client:
            result = await GithubTrendingAdapter(http=client, options={}).fetch()

    assert [item.raw_payload["language"] for item in result] == ["Python", "Python"]


@pytest.mark.asyncio
async def test_gh_trending_empty_html_raises_source_error() -> None:
    empty_html = "<html><body></body></html>"
    with respx.mock() as mock:
        mock.get(TRENDING_URL).respond(status_code=200, text=empty_html)
        mock.get(PYTHON_TRENDING_URL).respond(status_code=200, text=empty_html)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await GithubTrendingAdapter(http=client, options={}).fetch()
