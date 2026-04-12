from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ai_dashboard.sources.arxiv import ArxivAdapter
from ai_dashboard.storage.db import Database


async def main() -> int:
    db_path = Path("/tmp/ai_dashboard_smoke.db")
    for ext in ("", "-wal", "-shm", "-journal"):
        p = Path(str(db_path) + ext)
        if p.exists():
            p.unlink()

    db = Database(db_path)
    await db.connect()
    await db.init_schema()
    assert (await db.pragma("journal_mode")).lower() == "wal", "WAL not enabled"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        headers={"User-Agent": "ai-dashboard/0.1 (+smoke test)"},
    ) as http:
        adapter = ArxivAdapter(http=http, options={})
        items = await adapter.fetch()
        print(f"[smoke] arxiv fetch returned {len(items)} items")
        assert len(items) > 0, "arxiv returned zero items"

        n1 = await db.upsert_items(items)
        print(f"[smoke] first upsert: new_count={n1}")
        assert n1 == len(items), f"first upsert should insert all, got {n1}"

        n2 = await db.upsert_items(items)
        print(f"[smoke] second upsert: new_count={n2} (expect 0)")
        assert n2 == 0, f"second upsert should be idempotent, got {n2}"

        read_back = await db.get_items(limit=500)
        print(f"[smoke] read back: {len(read_back)} items")
        assert len(read_back) == len(items), "round-trip mismatch"

    await db.close()
    assert not (db_path.parent / (db_path.name + "-journal")).exists(), (
        "rollback journal leaked"
    )
    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
