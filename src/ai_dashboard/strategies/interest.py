from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from ai_dashboard.ai_service import AIService
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy


class InterestFilterStrategy:
    """Score items against NL interests via LLM, sort by relevance."""

    name: str
    _ai: AIService
    _interests: str
    _base: FeedListStrategy
    _cache: dict[str, float]

    def __init__(
        self,
        ai_service: AIService,
        interests: str,
        base_strategy: FeedListStrategy,
    ) -> None:
        self.name = f"interest-{getattr(base_strategy, 'name', 'strategy')}"
        self._ai = ai_service
        self._interests = interests.strip()
        self._base = base_strategy
        self._cache: dict[str, float] = {}

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        all_items = await self._base.items(db, now)
        if not self._ai.is_enabled or not self._interests:
            return all_items

        unscored = [item for item in all_items if item.source_uid not in self._cache]
        if unscored:
            scores = await self._score_batch(unscored)
            self._cache.update(scores)

        scored_items = [
            (self._cache.get(item.source_uid, 0.5), item) for item in all_items
        ]
        scored_items.sort(key=lambda entry: entry[0], reverse=True)
        return [item for score, item in scored_items if score >= 0.3]

    async def _score_batch(
        self, items: list[FeedItem], batch_size: int = 20
    ) -> dict[str, float]:
        """Score items in batches to minimize API calls."""
        results: dict[str, float] = {}

        for index in range(0, len(items), batch_size):
            batch = items[index : index + batch_size]
            titles = {item.source_uid: item.title for item in batch}

            response = await self._ai.complete_json(
                system_prompt=(
                    "You are a relevance scorer. Score each news item's relevance "
                    "to the user's interests on a 0.0-1.0 scale. Return JSON: "
                    '{"scores": {"id1": 0.8, "id2": 0.2}}'
                ),
                user_prompt=(
                    f"User interests: {self._interests}\n\n"
                    f"Items to score:\n{json.dumps(titles, indent=2)}"
                ),
            )

            raw_scores = response.get("scores", {})
            if isinstance(raw_scores, dict):
                for uid, score in cast(dict[Any, Any], raw_scores).items():
                    try:
                        results[str(uid)] = float(score)
                    except (TypeError, ValueError):
                        results[str(uid)] = 0.5

            for item in batch:
                if item.source_uid not in results:
                    results[item.source_uid] = 0.5

        return results
