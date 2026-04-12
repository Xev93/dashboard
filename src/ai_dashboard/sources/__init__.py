from __future__ import annotations

from importlib import import_module
from typing import Any

import httpx

_ADAPTER_SPECS: dict[str, tuple[str, str]] = {
    "arxiv": ("ai_dashboard.sources.arxiv", "ArxivAdapter"),
    "hn": ("ai_dashboard.sources.hackernews", "HackerNewsAdapter"),
    "github_trending": (
        "ai_dashboard.sources.github_trending",
        "GithubTrendingAdapter",
    ),
    "huggingface": ("ai_dashboard.sources.huggingface", "HuggingFaceAdapter"),
    "lab_blog": ("ai_dashboard.sources.lab_blog", "LabBlogAdapter"),
    "newsletter": ("ai_dashboard.sources.newsletter", "NewsletterAdapter"),
    "papers_with_code": (
        "ai_dashboard.sources.papers_with_code",
        "PapersWithCodeAdapter",
    ),
    "reddit": ("ai_dashboard.sources.reddit", "RedditAdapter"),
}


def _load_adapter(kind: str) -> type:
    module_name, class_name = _ADAPTER_SPECS[kind]
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class if isinstance(adapter_class, type) else type(adapter_class)


def build_adapter(kind: str, http: httpx.AsyncClient, options: dict[str, Any]) -> Any:
    if kind not in _ADAPTER_SPECS:
        raise ValueError(
            f"Unknown source kind: {kind!r}. Known: {sorted(_ADAPTER_SPECS)}"
        )
    return _load_adapter(kind)(http=http, options=options)


def available_kinds() -> list[str]:
    return sorted(_ADAPTER_SPECS)
