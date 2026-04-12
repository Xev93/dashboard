from __future__ import annotations

from typing import Any

import httpx

from ai_dashboard.sources.arxiv import ArxivAdapter
from ai_dashboard.sources.github_trending import GithubTrendingAdapter
from ai_dashboard.sources.hackernews import HackerNewsAdapter
from ai_dashboard.sources.huggingface import HuggingFaceAdapter
from ai_dashboard.sources.newsletter import NewsletterAdapter

_REGISTRY: dict[str, type] = {
    "arxiv": ArxivAdapter,
    "hn": HackerNewsAdapter,
    "github_trending": GithubTrendingAdapter,
    "huggingface": HuggingFaceAdapter,
    "newsletter": NewsletterAdapter,
}


def build_adapter(kind: str, http: httpx.AsyncClient, options: dict[str, Any]) -> Any:
    if kind not in _REGISTRY:
        raise ValueError(f"Unknown source kind: {kind!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[kind](http=http, options=options)


def available_kinds() -> list[str]:
    return sorted(_REGISTRY)
