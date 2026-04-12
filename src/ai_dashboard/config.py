from __future__ import annotations

import os
from importlib import import_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    tomllib = import_module("tomllib")
except ModuleNotFoundError:
    tomllib = import_module("tomli")


DEFAULT_HN_KEYWORDS = [
    "AI",
    "ML",
    "LLM",
    "GPT",
    "Claude",
    "OpenAI",
    "Anthropic",
    "neural",
    "transformer",
    "diffusion",
    "agent",
    "LoRA",
    "fine-tun",
    "embedding",
    "RAG",
    "deep learning",
    "prompt",
]

DEFAULT_NEWSLETTER_FEEDS = [
    "https://jack-clark.net/feed/",
    "https://www.deeplearning.ai/the-batch/feed/",
    "https://tldr.tech/api/rss/ai",
]


@dataclass
class SourceConfig:
    kind: str
    enabled: bool = True
    fetch_interval_seconds: int | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankingConfig:
    source_weight_first_party: float = 0.3
    source_weight_community: float = 0.0
    keyword_boost: float = 0.2
    recency_decay_hours: float = 24.0
    skip_penalty: float = 0.1
    skip_window: int = 50
    top_search_terms: int = 10


@dataclass
class AppConfig:
    sources: list[SourceConfig]
    db_path: Path
    log_level: str = "INFO"
    ranking: RankingConfig = field(default_factory=RankingConfig)

    @classmethod
    def defaults(cls) -> "AppConfig":
        return cls(
            sources=[
                SourceConfig(kind="arxiv"),
                SourceConfig(kind="hn", options={"keywords": DEFAULT_HN_KEYWORDS}),
                SourceConfig(kind="github_trending"),
                SourceConfig(kind="huggingface"),
                SourceConfig(kind="lab_blog"),
                SourceConfig(kind="papers_with_code"),
                SourceConfig(
                    kind="newsletter", options={"feeds": DEFAULT_NEWSLETTER_FEEDS}
                ),
                SourceConfig(
                    kind="reddit",
                    options={
                        "subreddits": ["MachineLearning", "artificial", "LocalLLaMA"]
                    },
                ),
            ],
            db_path=_default_db_path(),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        config_path = path or _default_config_path()
        if not config_path.exists():
            return cls.defaults()
        with config_path.open("rb") as f:
            data = tomllib.load(f)
        sources_raw = data.get("sources", [])
        sources: list[SourceConfig] = []
        for entry in sources_raw:
            sources.append(
                SourceConfig(
                    kind=entry["kind"],
                    enabled=entry.get("enabled", True),
                    fetch_interval_seconds=entry.get("fetch_interval_seconds"),
                    options=entry.get("options", {}),
                )
            )
        if not sources:
            sources = cls.defaults().sources
        db_path = Path(data.get("db_path", _default_db_path()))
        log_level = data.get("log_level", "INFO")
        ranking_raw = data.get("ranking", {})
        ranking = RankingConfig(
            **{
                k: v
                for k, v in ranking_raw.items()
                if k in RankingConfig.__dataclass_fields__
            }
        )
        return cls(
            sources=sources,
            db_path=db_path,
            log_level=log_level,
            ranking=ranking,
        )


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "ai-dashboard" / "config.toml"


def _default_db_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "ai-dashboard" / "cache.db"
