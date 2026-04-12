from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from datetime import datetime, timezone

import httpx
import pytest
import respx

from ai_dashboard.sources.lab_blog import LabBlogAdapter


def rss_fixture(
    *, title: str = "Test Post", link: str = "https://example.com/post-1"
) -> str:
    return f"""<?xml version=\"1.0\"?>
<rss version=\"2.0\">
<channel><title>Test Blog</title>
<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
  <description>Test description</description>
</item>
</channel></rss>
"""


EMPTY_RSS = """<?xml version=\"1.0\"?>
<rss version=\"2.0\"><channel><title>Empty Blog</title></channel></rss>
"""


@pytest.mark.asyncio
async def test_lab_blog_parses_rss() -> None:
    feed_url = "https://example.com/feed.xml"

    with respx.mock() as mock:
        _ = mock.get(feed_url).respond(status_code=200, text=rss_fixture())
        async with httpx.AsyncClient() as client:
            result = await LabBlogAdapter(
                http=client, options={"feeds": [feed_url]}
            ).fetch()

    assert len(result) == 1
    item = result[0]
    assert item.source_kind == "lab_blog"
    assert item.source_uid == "https://example.com/post-1"
    assert item.title == "Test Post"
    assert item.url == "https://example.com/post-1"
    assert item.published_at == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert item.raw_payload == {
        "feed_url": feed_url,
        "description": "Test description",
    }


def test_lab_blog_source_kind() -> None:
    assert LabBlogAdapter.source_kind == "lab_blog"


@pytest.mark.asyncio
async def test_lab_blog_handles_bad_feed() -> None:
    bad_feed = "https://example.com/bad.xml"
    good_feed = "https://example.com/good.xml"

    with respx.mock() as mock:
        _ = mock.get(bad_feed).respond(status_code=500)
        _ = mock.get(good_feed).respond(status_code=200, text=rss_fixture())
        async with httpx.AsyncClient() as client:
            result = await LabBlogAdapter(
                http=client, options={"feeds": [bad_feed, good_feed]}
            ).fetch()

    assert len(result) == 1
    assert result[0].url == "https://example.com/post-1"


@pytest.mark.asyncio
async def test_lab_blog_empty_feed() -> None:
    feed_url = "https://example.com/empty.xml"

    with respx.mock() as mock:
        _ = mock.get(feed_url).respond(status_code=200, text=EMPTY_RSS)
        async with httpx.AsyncClient() as client:
            result = await LabBlogAdapter(
                http=client, options={"feeds": [feed_url]}
            ).fetch()

    assert result == []


@pytest.mark.asyncio
async def test_lab_blog_custom_feeds() -> None:
    feed_one = "https://example.com/custom-1.xml"
    feed_two = "https://example.com/custom-2.xml"

    with respx.mock() as mock:
        route_one = mock.get(feed_one).respond(
            status_code=200,
            text=rss_fixture(title="Custom One", link="https://example.com/custom-one"),
        )
        route_two = mock.get(feed_two).respond(
            status_code=200,
            text=rss_fixture(title="Custom Two", link="https://example.com/custom-two"),
        )
        async with httpx.AsyncClient() as client:
            result = await LabBlogAdapter(
                http=client, options={"feeds": [feed_one, feed_two]}
            ).fetch()

    assert route_one.called
    assert route_two.called
    assert {item.url for item in result} == {
        "https://example.com/custom-one",
        "https://example.com/custom-two",
    }
