from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.storage.models import FeedItem


class GithubTrendingAdapter:
    kind = "github_trending"
    default_interval_seconds = 1800
    _user_agent = "ai-dashboard/0.1 (+https://github.com/user/ai-dashboard)"
    _endpoints = ("https://github.com/trending?since=daily",)
    _default_keywords = [
        "AI",
        "ML",
        "LLM",
        "GPT",
        "transformer",
        "diffusion",
        "neural",
        "agent",
        "agentic",
        "fine-tun",
        "embedding",
        "RAG",
        "prompt",
        "vector",
        "deep learning",
        "llama",
        "mistral",
        "claude",
    ]

    def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None:
        self.http = http
        self.options = options
        self.keyword_pattern = self._compile_keyword_pattern(
            options.get("keywords", self._default_keywords)
        )

    async def fetch(self) -> list[FeedItem]:
        try:
            responses = await asyncio.gather(
                *(self._fetch_endpoint(url) for url in self._endpoints)
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise SourceRateLimited(f"github trending rate limited: {e}") from e
            raise SourceError(
                f"github trending http {e.response.status_code}: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise SourceError(f"github trending fetch failed: {e}") from e

        items_by_uid: dict[str, FeedItem] = {}
        article_count = 0

        for response in responses:
            parsed_items, parsed_count = self._parse_response(response.text)
            article_count += parsed_count
            for item in parsed_items:
                items_by_uid[item.source_uid] = item

        if article_count == 0:
            raise SourceError(
                "github trending html structure changed; no articles parsed"
            )

        return list(items_by_uid.values())

    async def _fetch_endpoint(self, url: str) -> httpx.Response:
        response = await self.http.get(
            url,
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        return response

    def _parse_response(self, html: str) -> tuple[list[FeedItem], int]:
        tree = HTMLParser(html)
        articles = tree.css("article.Box-row")
        now = datetime.now(timezone.utc)
        items: list[FeedItem] = []

        for article in articles:
            repo_link = article.css_first("h2.h3 > a")
            href = repo_link.attributes.get("href", "") if repo_link else ""
            owner, name = self._parse_repo_href(href)
            if not owner or not name:
                continue

            description_node = article.css_first("p")
            description = (
                self._clean_text(description_node.text()) if description_node else ""
            )

            stars_node = article.css_first("a[href$='/stargazers']")
            stars = self._parse_stars(stars_node.text() if stars_node else "")

            language_node = article.css_first("span[itemprop='programmingLanguage']")
            language = self._clean_text(language_node.text()) if language_node else None

            haystack = " ".join(
                part for part in [name, description, language or ""] if part
            )
            if re.search(r"\b(?:not|no|anti)[-_\s]+ai\b", haystack, re.IGNORECASE):
                continue
            if not self.keyword_pattern.search(haystack):
                continue

            items.append(
                FeedItem(
                    id=None,
                    source_kind="github_trending",
                    source_uid=f"{owner}/{name}",
                    title=f"{owner}/{name}",
                    url=f"https://github.com/{owner}/{name}",
                    published_at=now,
                    raw_payload={
                        "owner": owner,
                        "name": name,
                        "description": description,
                        "stars": stars,
                        "language": language,
                    },
                )
            )

        return items, len(articles)

    @staticmethod
    def _compile_keyword_pattern(keywords: Any) -> re.Pattern[str]:
        values = [str(keyword) for keyword in keywords if str(keyword).strip()]
        if not values:
            values = GithubTrendingAdapter._default_keywords
        escaped = [re.escape(value) for value in values]
        return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)

    @staticmethod
    def _parse_repo_href(href: str) -> tuple[str, str]:
        parts = [part for part in href.strip().split("/") if part]
        if len(parts) < 2:
            return "", ""
        return parts[0], parts[1]

    @staticmethod
    def _parse_stars(text: str) -> int:
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ",")
        if not cleaned:
            return 0
        return int(cleaned.replace(",", ""))

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(value.split())
