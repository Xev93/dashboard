from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.chronological import ChronologicalAllSourcesStrategy


@pytest.mark.asyncio
async def test_chronological_strategy_returns_items(
    db: Database, sample_feed_items: list[FeedItem]
) -> None:
    await db.upsert_items(sample_feed_items)

    strategy = ChronologicalAllSourcesStrategy(limit=500)
    items = await strategy.items(db, datetime.now(timezone.utc))

    assert len(items) == 3
    assert [item.source_uid for item in items] == [
        "2604.12345v1",
        "42000001",
        "openai/example-llm-agents",
    ]
    assert all(items[i].published_at >= items[i + 1].published_at for i in range(2))


@pytest.mark.asyncio
async def test_feed_list_widget_works_with_custom_strategy(
    db: Database, sample_feed_items: list[FeedItem]
) -> None:
    class OnlyArxivStrategy:
        name = "only-arxiv"

        async def items(self, db: Database, now: datetime) -> list[FeedItem]:
            return [
                item
                for item in await db.get_items(limit=500)
                if item.source_kind == "arxiv"
            ]

    await db.upsert_items(sample_feed_items)

    strategy = OnlyArxivStrategy()
    items = await strategy.items(db, datetime.now(timezone.utc))

    assert len(items) == 1
    assert items[0].source_kind == "arxiv"
    assert items[0].source_uid == "2604.12345v1"


def test_feed_list_widget_imports_only_strategy_base() -> None:
    path = Path(__file__).resolve().parents[1] / "src/ai_dashboard/widgets/feed_list.py"
    src = path.read_text()
    tree = ast.parse(src)

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("ai_dashboard.strategies"):
                if module != "ai_dashboard.strategies.base":
                    violations.append(f"forbidden import-from module: {module}")
                if module == "ai_dashboard.strategies" and node.names:
                    violations.append(
                        "bare from ai_dashboard.strategies import X is forbidden"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("ai_dashboard.strategies"):
                    if alias.name != "ai_dashboard.strategies.base":
                        violations.append(f"forbidden import: {alias.name}")

    if "strategies.chronological" in src:
        violations.append("feed_list.py references strategies.chronological")
    if "ChronologicalAllSourcesStrategy" in src:
        violations.append("feed_list.py references ChronologicalAllSourcesStrategy")

    if violations:
        print("\n".join(violations))

    assert not violations
