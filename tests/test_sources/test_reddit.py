from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from datetime import datetime, timezone

import httpx
import pytest
import respx

from ai_dashboard.sources.reddit import RedditAdapter


def reddit_fixture(
    *,
    name: str = "t3_abc123",
    title: str = "Test Post",
    permalink: str = "/r/test/comments/abc123/test_post/",
    subreddit: str = "test",
    score: int = 42,
) -> dict[str, object]:
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "name": name,
                        "title": title,
                        "permalink": permalink,
                        "created_utc": 1704067200,
                        "score": score,
                        "num_comments": 5,
                        "subreddit": subreddit,
                        "selftext": "Test body",
                    }
                }
            ]
        }
    }


def subreddit_url(name: str) -> str:
    return f"https://www.reddit.com/r/{name}/hot.json?limit=25"


@pytest.mark.asyncio
async def test_reddit_parses_posts() -> None:
    with respx.mock() as mock:
        _ = mock.get(subreddit_url("test")).respond(
            status_code=200, json=reddit_fixture()
        )
        async with httpx.AsyncClient() as client:
            result = await RedditAdapter(
                http=client, options={"subreddits": ["test"]}
            ).fetch()

    assert len(result) == 1
    item = result[0]
    assert item.source_kind == "reddit"
    assert item.source_uid == "reddit_t3_abc123"
    assert item.title == "Test Post"
    assert item.url == "https://reddit.com/r/test/comments/abc123/test_post/"
    assert item.published_at == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert item.raw_payload == {
        "score": 42,
        "num_comments": 5,
        "subreddit": "test",
        "selftext": "Test body",
    }


def test_reddit_source_kind() -> None:
    assert RedditAdapter.source_kind == "reddit"


@pytest.mark.asyncio
async def test_reddit_handles_429() -> None:
    with respx.mock() as mock:
        _ = mock.get(subreddit_url("test")).respond(status_code=429, json={})
        async with httpx.AsyncClient() as client:
            result = await RedditAdapter(
                http=client, options={"subreddits": ["test"]}
            ).fetch()

    assert result == []


@pytest.mark.asyncio
async def test_reddit_score_in_payload() -> None:
    with respx.mock() as mock:
        _ = mock.get(subreddit_url("test")).respond(
            status_code=200,
            json=reddit_fixture(score=99),
        )
        async with httpx.AsyncClient() as client:
            result = await RedditAdapter(
                http=client, options={"subreddits": ["test"]}
            ).fetch()

    assert "score" in result[0].raw_payload
    assert result[0].raw_payload["score"] == 99


@pytest.mark.asyncio
async def test_reddit_custom_subreddits() -> None:
    first = "OpenAI"
    second = "LocalLLaMA"

    with respx.mock() as mock:
        route_one = mock.get(subreddit_url(first)).respond(
            status_code=200,
            json=reddit_fixture(
                name="t3_first",
                title="First Post",
                permalink="/r/OpenAI/comments/first/post/",
                subreddit=first,
            ),
        )
        route_two = mock.get(subreddit_url(second)).respond(
            status_code=200,
            json=reddit_fixture(
                name="t3_second",
                title="Second Post",
                permalink="/r/LocalLLaMA/comments/second/post/",
                subreddit=second,
            ),
        )
        async with httpx.AsyncClient() as client:
            result = await RedditAdapter(
                http=client, options={"subreddits": [first, second]}
            ).fetch()

    assert route_one.called
    assert route_two.called
    assert {item.raw_payload["subreddit"] for item in result} == {first, second}
