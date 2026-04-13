from __future__ import annotations

import asyncio
import ipaddress

import httpx
from selectolax.parser import HTMLParser
from urllib.parse import urlparse

from ai_dashboard import USER_AGENT
from ai_dashboard.source_catalog import CATALOG_BY_KIND
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


MAX_CONTENT_LENGTH = 15_000
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "169.254.169.254",
    }
)


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname in _BLOCKED_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass
    return True


class ContentFetcher:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    async def stop(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def fetch_content(self, item: FeedItem) -> str:
        cached = await self._db.get_cached_content(item.source_kind, item.source_uid)
        if cached is not None:
            return cached

        if self._http is None:
            return "[Content fetcher not started]"

        try:
            content = await self._fetch_by_kind(item)
        except Exception as e:
            return f"[Failed to fetch content: {e}]"

        if content:
            await self._db.set_cached_content(
                item.source_kind, item.source_uid, content
            )
        return content or "[No content available]"

    async def _fetch_by_kind(self, item: FeedItem) -> str:
        source_def = CATALOG_BY_KIND.get(item.source_kind)
        if source_def is None:
            return ""

        mode = source_def.content_mode
        if mode == "arxiv":
            return await self._fetch_arxiv(item)
        elif mode == "github_readme":
            return await self._fetch_github_readme(item)
        elif mode == "hf_card":
            return await self._fetch_hf_card(item)
        elif mode == "web_article":
            return await self._fetch_web_article(item.url)
        elif mode == "core_pdf":
            return await self._fetch_core_pdf(item)
        elif mode.startswith("payload:"):
            return self._fetch_from_payload(item, mode.split(":", 1)[1])
        return ""

    async def _fetch_core_pdf(self, item: FeedItem) -> str:
        abstract = (item.raw_payload or {}).get("abstract", "")
        page_url = item.url or ""
        is_pdf = page_url.lower().endswith(".pdf")
        if not is_pdf and page_url and _is_safe_url(page_url):
            text = await self._fetch_web_article(page_url)
            if text and not text.startswith("["):
                if abstract:
                    return f"{abstract}\n\n---\n\n{text}"
                return text
        if abstract:
            return abstract
        return ""

    @staticmethod
    def _fetch_from_payload(item: FeedItem, key: str) -> str:
        text = item.raw_payload.get(key, "")
        if not text:
            return ""
        if isinstance(text, str):
            return text
        return str(text)

    async def _fetch_arxiv(self, item: FeedItem) -> str:
        http = self._http
        if http is None:
            return item.raw_payload.get("abstract", "")

        arxiv_id = item.raw_payload.get("arxiv_id", "")
        if not arxiv_id:
            return item.raw_payload.get("abstract", "")

        html_url = f"https://arxiv.org/html/{arxiv_id}"
        if not _is_safe_url(html_url):
            return item.raw_payload.get("abstract", "[No abstract available]")
        try:
            resp = await http.get(html_url)
            if resp.status_code == 200:
                tree = HTMLParser(resp.text)
                for tag in tree.css(
                    "script, style, nav, header, footer, .ltx_page_header, .ltx_page_footer"
                ):
                    tag.decompose()
                body = tree.css_first("article.ltx_document") or tree.css_first("body")
                if body:
                    text = body.text(separator="\n", strip=True)
                    if len(text) > MAX_CONTENT_LENGTH:
                        text = (
                            text[:MAX_CONTENT_LENGTH]
                            + "\n\n[... truncated at 15,000 chars]"
                        )
                    return text
        except httpx.HTTPError:
            pass

        return item.raw_payload.get("abstract", "[No abstract available]")

    async def _fetch_github_readme(self, item: FeedItem) -> str:
        http = self._http
        if http is None:
            return item.raw_payload.get("description", "")

        owner = item.raw_payload.get("owner", "")
        name = item.raw_payload.get("name", "")
        if not owner or not name:
            return item.raw_payload.get("description", "")

        for branch in ("main", "master"):
            url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/README.md"
            if not _is_safe_url(url):
                return item.raw_payload.get("description", "[README not found]")
            try:
                resp = await http.get(url)
                if resp.status_code == 200:
                    text = resp.text
                    if len(text) > MAX_CONTENT_LENGTH:
                        text = (
                            text[:MAX_CONTENT_LENGTH]
                            + "\n\n[... truncated at 15,000 chars]"
                        )
                    return text
            except httpx.HTTPError:
                continue

        return item.raw_payload.get("description", "[README not found]")

    async def _fetch_hf_card(self, item: FeedItem) -> str:
        http = self._http
        if http is None:
            return ""

        hf_kind = item.raw_payload.get("hf_kind", "model")
        hf_id = item.raw_payload.get("id", "")
        if not hf_id:
            return ""

        kind_plural = {"model": "models", "dataset": "datasets", "space": "spaces"}.get(
            hf_kind, "models"
        )
        readme_url = f"https://huggingface.co/{hf_id}/resolve/main/README.md"
        if not _is_safe_url(readme_url):
            return "[No card content available]"
        try:
            resp = await http.get(readme_url)
            if resp.status_code == 200:
                text = resp.text
                if len(text) > MAX_CONTENT_LENGTH:
                    text = text[:MAX_CONTENT_LENGTH] + "\n\n[... truncated]"
                return text
        except httpx.HTTPError:
            pass

        url = f"https://huggingface.co/api/{kind_plural}/{hf_id}"
        if not _is_safe_url(url):
            return "[No card content available]"
        try:
            resp = await http.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
            parts: list[str] = []
            if data.get("description"):
                parts.append(data["description"])
            card_data = data.get("cardData")
            if card_data:
                parts.append(f"\nCard metadata: {card_data}")
            return "\n".join(parts) if parts else "[No card content available]"
        except httpx.HTTPError as e:
            return f"[Failed to fetch HF card: {e}]"

    async def _fetch_web_article(self, url: str) -> str:
        http = self._http
        if http is None:
            return "[Content fetcher not started]"

        if not url or url.startswith("https://news.ycombinator.com"):
            return "[HN self-post — no external article]"

        try:
            import trafilatura
        except ImportError:
            return "[trafilatura not installed — cannot extract article]"

        try:
            if not _is_safe_url(url):
                return "[URL blocked by security policy]"
            resp = await http.get(url)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPError as e:
            return f"[Failed to fetch article: {e}]"

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(
                    trafilatura.extract,
                    html,
                    include_comments=False,
                    include_tables=True,
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            text = None
        if not text:
            tree = HTMLParser(html)
            for tag in tree.css("script, style, nav, header, footer"):
                tag.decompose()
            body = (
                tree.css_first("article")
                or tree.css_first("main")
                or tree.css_first("body")
            )
            text = (
                body.text(separator="\n", strip=True)
                if body
                else "[Could not extract content]"
            )

        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "\n\n[... truncated at 15,000 chars]"
        return text
