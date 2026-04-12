from pathlib import Path

import httpx
import pytest
import respx

from ai_dashboard.sources.newsletter import NewsletterAdapter


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "newsletter.xml"
FEED_URL = "https://example.com/fake-feed"


def _fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.mark.asyncio
async def test_newsletter_parses_feed() -> None:
    async with httpx.AsyncClient() as client:
        adapter = NewsletterAdapter(http=client, options={"feeds": [FEED_URL]})
        with respx.mock(assert_all_called=True) as mock:
            mock.get(FEED_URL).mock(
                return_value=httpx.Response(200, content=_fixture_bytes())
            )

            items = await adapter.fetch()

    assert len(items) == 2


@pytest.mark.asyncio
async def test_newsletter_source_uid_includes_feed_hash() -> None:
    async with httpx.AsyncClient() as client:
        adapter = NewsletterAdapter(http=client, options={"feeds": [FEED_URL]})
        with respx.mock(assert_all_called=True) as mock:
            mock.get(FEED_URL).mock(
                return_value=httpx.Response(200, content=_fixture_bytes())
            )

            items = await adapter.fetch()

    for item in items:
        prefix, _ = item.source_uid.split(":", 1)
        assert len(prefix) == 8
        int(prefix, 16)


@pytest.mark.asyncio
async def test_newsletter_raw_payload() -> None:
    async with httpx.AsyncClient() as client:
        adapter = NewsletterAdapter(http=client, options={"feeds": [FEED_URL]})
        with respx.mock(assert_all_called=True) as mock:
            mock.get(FEED_URL).mock(
                return_value=httpx.Response(200, content=_fixture_bytes())
            )

            items = await adapter.fetch()

    payload = items[0].raw_payload
    assert set(payload) >= {"publication", "summary", "pub_date", "feed_url"}
    assert payload["publication"] == "Import AI"
    assert payload["feed_url"] == FEED_URL


@pytest.mark.asyncio
async def test_newsletter_multiple_feeds() -> None:
    feed_urls = ["https://example.com/feed-a", "https://example.com/feed-b"]

    async with httpx.AsyncClient() as client:
        adapter = NewsletterAdapter(http=client, options={"feeds": feed_urls})
        with respx.mock(assert_all_called=True) as mock:
            for url in feed_urls:
                mock.get(url).mock(
                    return_value=httpx.Response(200, content=_fixture_bytes())
                )

            items = await adapter.fetch()

    assert len(items) == 4
    assert {item.source_uid.split(":", 1)[0] for item in items} == {
        items[0].source_uid.split(":", 1)[0],
        items[2].source_uid.split(":", 1)[0],
    }
    assert items[0].source_uid.split(":", 1)[0] != items[2].source_uid.split(":", 1)[0]


@pytest.mark.asyncio
async def test_newsletter_one_feed_failure_does_not_break_others(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ok_url = "https://example.com/feed-ok"
    bad_url = "https://example.com/feed-bad"

    async with httpx.AsyncClient() as client:
        adapter = NewsletterAdapter(http=client, options={"feeds": [bad_url, ok_url]})
        with respx.mock(assert_all_called=True) as mock:
            mock.get(bad_url).mock(return_value=httpx.Response(500))
            mock.get(ok_url).mock(
                return_value=httpx.Response(200, content=_fixture_bytes())
            )

            items = await adapter.fetch()

    captured = capsys.readouterr()
    assert len(items) == 2
    assert bad_url in captured.err
    assert "failed" in captured.err
