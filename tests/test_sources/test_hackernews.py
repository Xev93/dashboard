from __future__ import annotations

from pathlib import Path
import json

import httpx
import pytest
import respx

from ai_dashboard.sources.hackernews import HackerNewsAdapter


FIXTURES = Path(__file__).parents[1] / "fixtures"
TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"


def load_json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_hn_filters_ai_keywords() -> None:
    topstories = load_json("hn_topstories.json")
    with respx.mock() as mock:
        mock.get(TOPSTORIES_URL).respond(status_code=200, json=topstories)
        for story_id in [42000001, 42000002, 42000003, 42000004]:
            mock.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            ).respond(status_code=200, json=load_json(f"hn_item_{story_id}.json"))
        async with httpx.AsyncClient() as client:
            result = await HackerNewsAdapter(http=client, options={}).fetch()

    assert len(result) == 3
    assert [item.source_uid for item in result] == ["42000001", "42000002", "42000004"]


@pytest.mark.asyncio
async def test_hn_source_uid_is_story_id_string() -> None:
    topstories = load_json("hn_topstories.json")
    with respx.mock() as mock:
        mock.get(TOPSTORIES_URL).respond(status_code=200, json=topstories)
        for story_id in [42000001, 42000002, 42000003, 42000004]:
            mock.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            ).respond(status_code=200, json=load_json(f"hn_item_{story_id}.json"))
        async with httpx.AsyncClient() as client:
            result = await HackerNewsAdapter(http=client, options={}).fetch()

    assert all(item.source_uid.isdigit() for item in result)
    assert all(item.source_kind == "hn" for item in result)


@pytest.mark.asyncio
async def test_hn_raw_payload_has_expected_fields() -> None:
    topstories = load_json("hn_topstories.json")
    with respx.mock() as mock:
        mock.get(TOPSTORIES_URL).respond(status_code=200, json=topstories)
        for story_id in [42000001, 42000002, 42000003, 42000004]:
            mock.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            ).respond(status_code=200, json=load_json(f"hn_item_{story_id}.json"))
        async with httpx.AsyncClient() as client:
            result = await HackerNewsAdapter(http=client, options={}).fetch()

    payload = result[0].raw_payload
    assert set(payload) >= {"points", "comment_count", "submitted_by", "hn_id"}
    assert payload["points"] == 342


@pytest.mark.asyncio
async def test_hn_custom_keyword_list() -> None:
    topstories = load_json("hn_topstories.json")
    with respx.mock() as mock:
        mock.get(TOPSTORIES_URL).respond(status_code=200, json=topstories)
        for story_id in [42000001, 42000002, 42000003, 42000004]:
            mock.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            ).respond(status_code=200, json=load_json(f"hn_item_{story_id}.json"))
        async with httpx.AsyncClient() as client:
            result = await HackerNewsAdapter(
                http=client, options={"keywords": ["sourdough"]}
            ).fetch()

    assert [item.source_uid for item in result] == ["42000003"]
