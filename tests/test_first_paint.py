from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.chronological import ChronologicalAllSourcesStrategy


@pytest.mark.asyncio
async def test_first_paint_under_200ms(tmp_path: Path) -> None:
    db_path = tmp_path / "first_paint.db"
    seed_db = Database(db_path)
    await seed_db.connect()
    await seed_db.init_schema()
    items = [
        FeedItem(
            id=None,
            source_kind="arxiv",
            source_uid=f"seed-{i}",
            title=f"Paper {i}",
            url=f"http://arxiv.org/abs/{i}",
            published_at=datetime.now(timezone.utc),
            raw_payload={"idx": i},
        )
        for i in range(500)
    ]
    await seed_db.upsert_items(items)
    await seed_db.close()

    t0 = time.perf_counter()
    db = Database(db_path)
    await db.connect()
    await db.init_schema()
    strategy = ChronologicalAllSourcesStrategy(limit=500)
    result = await strategy.items(db, datetime.now(timezone.utc))
    t1 = time.perf_counter()
    await db.close()

    elapsed_ms = (t1 - t0) * 1000.0
    assert len(result) == 500, f"expected 500 items, got {len(result)}"
    assert elapsed_ms < 200.0, (
        f"first-paint path took {elapsed_ms:.1f}ms, exceeds 200ms SLO"
    )
