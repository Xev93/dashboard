from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from ai_dashboard.storage.db import Database
from ai_dashboard.workers import PollingOrchestrator


async def _fake_on_new_items(count: int, source_kind: str) -> None:
    pass


@pytest.mark.asyncio
async def test_orchestrator_stops_under_2s(tmp_path: Path) -> None:
    db = Database(tmp_path / "shutdown.db")
    await db.connect()
    await db.init_schema()

    # Use only the newsletter source since it hits remote but the adapter handles
    # per-feed failures gracefully. Actually, use huggingface with a bogus option
    # that will likely 404 fast. For deterministic behavior, pass NO adapter specs
    # so start() spawns zero tasks — we're testing the orchestrator shutdown path,
    # not adapter-specific behavior.
    orch = PollingOrchestrator(adapter_specs=[], db=db, on_new_items=_fake_on_new_items)
    await orch.start()
    # Let the event loop cycle briefly
    await asyncio.sleep(0.05)

    t0 = time.perf_counter()
    await orch.stop(timeout=2.0)
    elapsed = time.perf_counter() - t0

    await db.close()
    assert elapsed < 2.0, f"orchestrator.stop() took {elapsed:.2f}s, exceeds 2s SLO"


@pytest.mark.asyncio
async def test_orchestrator_stop_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "shutdown2.db")
    await db.connect()
    await db.init_schema()

    orch = PollingOrchestrator(adapter_specs=[], db=db, on_new_items=_fake_on_new_items)
    await orch.start()
    await orch.stop(timeout=2.0)
    # second stop should not raise
    await orch.stop(timeout=2.0)
    await db.close()
