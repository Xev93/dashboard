from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from ai_dashboard.source_catalog import CATALOG_BY_KIND, SOURCE_CATALOG

try:
    tomllib = import_module("tomllib")
except ModuleNotFoundError:
    tomllib = import_module("tomli")


DEFAULT_HN_KEYWORDS = list(CATALOG_BY_KIND["hn"].default_options["keywords"])
DEFAULT_NEWSLETTER_FEEDS = list(CATALOG_BY_KIND["newsletter"].default_options["feeds"])


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
                SourceConfig(
                    kind=source.kind,
                    enabled=source.enabled,
                    options=dict(source.default_options),
                )
                for source in SOURCE_CATALOG
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
        else:
            configured_kinds = {s.kind for s in sources}
            for source in SOURCE_CATALOG:
                if source.kind not in configured_kinds:
                    sources.append(
                        SourceConfig(
                            kind=source.kind,
                            enabled=source.enabled,
                            options=dict(source.default_options),
                        )
                    )
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
