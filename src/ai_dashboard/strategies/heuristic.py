from __future__ import annotations

import math
from datetime import datetime
from typing import AbstractSet, Protocol, cast

from ai_dashboard.config import RankingConfig
from ai_dashboard.source_catalog import ENGAGEMENT_KEYS, FIRST_PARTY_KINDS
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class _SupportsHeuristicQueries(Protocol):
    async def get_top_search_terms(self, limit: int = 10) -> list[str]: ...

    async def get_skip_counts(self, last_n_views: int = 50) -> dict[str, int]: ...

    async def get_engagement_percentiles(self) -> dict[str, float]: ...


class HeuristicRankingStrategy:
    """Rank items by heuristic score: engagement + source_weight + keyword_boost + recency_decay - skip_penalty."""

    FIRST_PARTY: AbstractSet[str] = FIRST_PARTY_KINDS
    name: str = "heuristic-ranking"
    _config: RankingConfig
    _limit: int

    def __init__(self, config: RankingConfig, limit: int = 500) -> None:
        self._config = config
        self._limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        all_items = await db.get_items(limit=self._limit)
        ranking_db = cast(_SupportsHeuristicQueries, cast(object, db))
        top_terms = await ranking_db.get_top_search_terms(
            limit=self._config.top_search_terms
        )
        skip_counts = await ranking_db.get_skip_counts(
            last_n_views=self._config.skip_window
        )
        percentiles = await ranking_db.get_engagement_percentiles()

        scored: list[tuple[float, FeedItem]] = []
        for item in all_items:
            score = self._compute_score(item, now, top_terms, skip_counts, percentiles)
            scored.append((score, item))
        scored.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, item in scored]

    def _compute_score(
        self,
        item: FeedItem,
        now: datetime,
        top_terms: list[str],
        skip_counts: dict[str, int],
        percentiles: dict[str, float],
    ) -> float:
        eng = self._engagement_normalized(item, percentiles)
        sw = (
            self._config.source_weight_first_party
            if item.source_kind in self.FIRST_PARTY
            else self._config.source_weight_community
        )
        kb = self._keyword_boost(item, top_terms)
        rd = self._recency_decay(item, now)
        sp = self._skip_penalty(item, skip_counts)
        return eng + sw + kb + rd - sp

    def _engagement_normalized(
        self, item: FeedItem, percentiles: dict[str, float]
    ) -> float:
        key = ENGAGEMENT_KEYS.get(item.source_kind)
        if key is None:
            return 0.0
        raw_value = item.raw_payload.get(key, 0)
        value = float(raw_value) if isinstance(raw_value, int | float) else 0.0
        p95 = percentiles.get(item.source_kind, 1.0) or 1.0
        return min(value / p95, 1.0)

    def _keyword_boost(self, item: FeedItem, top_terms: list[str]) -> float:
        if not top_terms:
            return 0.0
        title_lower = (item.title or "").lower()
        matches = sum(1 for term in top_terms if term.lower() in title_lower)
        return matches * self._config.keyword_boost

    def _recency_decay(self, item: FeedItem, now: datetime) -> float:
        hours_old = (now - item.published_at).total_seconds() / 3600
        return math.exp(-hours_old / self._config.recency_decay_hours)

    def _skip_penalty(self, item: FeedItem, skip_counts: dict[str, int]) -> float:
        count = skip_counts.get(item.source_kind, 0)
        return count * self._config.skip_penalty
