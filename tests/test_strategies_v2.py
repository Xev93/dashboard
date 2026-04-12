from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, get_type_hints

import pytest

from ai_dashboard.config import RankingConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy
from ai_dashboard.strategies.by_source import BySourceStrategy
from ai_dashboard.strategies.chronological import ChronologicalAllSourcesStrategy
from ai_dashboard.strategies.filtered import FilteredStrategy
from ai_dashboard.strategies.heuristic import HeuristicRankingStrategy


class StubDatabase:
    def __init__(
        self,
        items: list[FeedItem],
        *,
        top_terms: list[str] | None = None,
        skip_counts: dict[str, int] | None = None,
        percentiles: dict[str, float] | None = None,
    ) -> None:
        self._items = items
        self._top_terms = top_terms or []
        self._skip_counts = skip_counts or {}
        self._percentiles = percentiles or {}

    async def get_items(self, limit: int = 500) -> list[FeedItem]:
        return self._items[:limit]

    async def record_item_view(
        self, source_kind: str, source_uid: str, action: str
    ) -> None:
        if action == "skipped":
            self._skip_counts[source_kind] = self._skip_counts.get(source_kind, 0) + 1

    async def record_search_term(self, term: str) -> None:
        self._top_terms.insert(0, term)

    async def get_top_search_terms(self, limit: int = 10) -> list[str]:
        return self._top_terms[:limit]

    async def get_skip_counts(self, last_n_views: int = 50) -> dict[str, int]:
        return dict(self._skip_counts)

    async def get_engagement_percentiles(self) -> dict[str, float]:
        return dict(self._percentiles)


def make_item(
    source_kind: str,
    source_uid: str,
    title: str,
    *,
    hours_old: float = 0,
    url: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> FeedItem:
    now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    return FeedItem(
        id=None,
        source_kind=source_kind,
        source_uid=source_uid,
        title=title,
        url=url or f"https://example.com/{source_uid}",
        published_at=now - timedelta(hours=hours_old),
        raw_payload=raw_payload or {},
    )


@pytest.mark.asyncio
async def test_by_source_filters_single_kind() -> None:
    db = StubDatabase(
        [
            make_item("hn", "hn-1", "Hacker News item"),
            make_item("arxiv", "ax-1", "Arxiv item"),
            make_item("hn", "hn-2", "Another HN item"),
        ]
    )

    items = await BySourceStrategy("hn").items(db, datetime.now(timezone.utc))

    assert [item.source_uid for item in items] == ["hn-1", "hn-2"]
    assert all(item.source_kind == "hn" for item in items)


@pytest.mark.asyncio
async def test_by_source_empty_for_unknown() -> None:
    db = StubDatabase([make_item("hn", "hn-1", "Hacker News item")])

    items = await BySourceStrategy("nonexistent").items(db, datetime.now(timezone.utc))

    assert items == []


@pytest.mark.asyncio
async def test_heuristic_first_party_weight() -> None:
    now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    arxiv_item = make_item("arxiv", "ax-1", "Paper", hours_old=1)
    hn_item = make_item("hn", "hn-1", "Post", hours_old=1, raw_payload={"points": 0})
    db = StubDatabase([hn_item, arxiv_item], percentiles={"hn": 100.0})

    items = await HeuristicRankingStrategy(RankingConfig()).items(db, now)

    assert [item.source_uid for item in items[:2]] == ["ax-1", "hn-1"]


@pytest.mark.asyncio
async def test_heuristic_recency_decay() -> None:
    now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    recent = make_item(
        "hn", "hn-new", "Recent", hours_old=1, raw_payload={"points": 50}
    )
    old = make_item("hn", "hn-old", "Old", hours_old=48, raw_payload={"points": 50})
    db = StubDatabase([old, recent], percentiles={"hn": 100.0})

    items = await HeuristicRankingStrategy(RankingConfig()).items(db, now)

    assert [item.source_uid for item in items[:2]] == ["hn-new", "hn-old"]


@pytest.mark.asyncio
async def test_heuristic_keyword_boost() -> None:
    now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    match = make_item(
        "hn", "hn-match", "Claude agent release", raw_payload={"points": 50}
    )
    plain = make_item("hn", "hn-plain", "General AI update", raw_payload={"points": 50})
    db = StubDatabase(
        [plain, match],
        top_terms=["claude"],
        percentiles={"hn": 100.0},
    )

    items = await HeuristicRankingStrategy(RankingConfig()).items(db, now)

    assert [item.source_uid for item in items[:2]] == ["hn-match", "hn-plain"]


@pytest.mark.asyncio
async def test_heuristic_skip_penalty() -> None:
    now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    penalized = make_item("hn", "hn-1", "Penalized", raw_payload={"points": 50})
    clean = make_item("reddit", "rd-1", "Clean", raw_payload={"score": 50})
    db = StubDatabase(
        [penalized, clean],
        skip_counts={"hn": 2},
        percentiles={"hn": 100.0, "reddit": 100.0},
    )

    items = await HeuristicRankingStrategy(RankingConfig()).items(db, now)

    assert [item.source_uid for item in items[:2]] == ["rd-1", "hn-1"]


@pytest.mark.asyncio
async def test_filtered_matches_title() -> None:
    db = StubDatabase(
        [
            make_item("hn", "hn-1", "Claude launches tools"),
            make_item("hn", "hn-2", "General update"),
        ]
    )

    strategy = FilteredStrategy(ChronologicalAllSourcesStrategy(), "claude")
    items = await strategy.items(db, datetime.now(timezone.utc))

    assert [item.source_uid for item in items] == ["hn-1"]


@pytest.mark.asyncio
async def test_filtered_case_insensitive() -> None:
    db = StubDatabase([make_item("hn", "hn-1", "OpenAI ships new model")])

    strategy = FilteredStrategy(ChronologicalAllSourcesStrategy(), "openai")
    items = await strategy.items(db, datetime.now(timezone.utc))

    assert [item.source_uid for item in items] == ["hn-1"]


@pytest.mark.asyncio
async def test_filtered_no_match_empty() -> None:
    db = StubDatabase([make_item("hn", "hn-1", "OpenAI ships new model")])

    strategy = FilteredStrategy(ChronologicalAllSourcesStrategy(), "anthropic")
    items = await strategy.items(db, datetime.now(timezone.utc))

    assert items == []


def test_all_strategies_satisfy_protocol() -> None:
    class _SignatureFilteredBase:
        name = "base"

        async def items(self, db: Database, now: datetime) -> list[FeedItem]:
            return []

    strategies = [
        ChronologicalAllSourcesStrategy(),
        BySourceStrategy("hn"),
        HeuristicRankingStrategy(RankingConfig()),
        FilteredStrategy(_SignatureFilteredBase(), "hn"),
    ]

    for strategy in strategies:
        assert isinstance(strategy.name, str)
        assert callable(strategy.items)

        signature = inspect.signature(type(strategy).items)
        hints = get_type_hints(type(strategy).items)
        parameters = list(signature.parameters.values())
        assert [parameter.name for parameter in parameters] == ["self", "db", "now"]
        assert hints["db"] is Database
        assert hints["now"] is datetime
        assert hints["return"] == list[FeedItem]

        typed_strategy: FeedListStrategy = strategy
        assert typed_strategy is strategy
