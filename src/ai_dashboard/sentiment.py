"""Batch sentiment analysis for feed items."""

from __future__ import annotations

import json
import logging

from ai_dashboard.ai_service import AIService
from ai_dashboard.storage.db import Database

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral", "controversial"})
SENTIMENT_INDICATORS = {
    "positive": "😊",
    "negative": "😟",
    "neutral": "😐",
    "controversial": "🔥",
    None: " ",
}


async def analyze_sentiments(ai: AIService, db: Database, batch_size: int = 30) -> int:
    """Analyze sentiment for unprocessed items. Returns count analyzed."""
    if not ai.is_enabled:
        return 0

    items = await db.get_unanalyzed_items(limit=batch_size)
    if not items:
        return 0

    titles = {str(item.id): item.title for item in items if item.id is not None}
    if not titles:
        return 0

    result = await ai.complete_json(
        system_prompt=(
            "Classify each news headline's sentiment as exactly one of: "
            "positive, negative, neutral, controversial. Return JSON: "
            '{"sentiments": {"id1": "positive", "id2": "negative", ...}}'
        ),
        user_prompt=f"Headlines:\n{json.dumps(titles, indent=2)}",
    )

    sentiments = result.get("sentiments", {})
    if not isinstance(sentiments, dict):
        logger.warning("Sentiment analyzer returned invalid payload: %r", sentiments)
        return 0

    bulk: dict[int, str] = {}
    for id_str, sentiment in sentiments.items():
        try:
            item_id = int(id_str)
        except (ValueError, TypeError):
            continue
        if sentiment in VALID_SENTIMENTS:
            bulk[item_id] = sentiment

    if bulk:
        await db.set_sentiments_bulk(bulk)

    return len(bulk)
