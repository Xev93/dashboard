from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from ai_dashboard import USER_AGENT
from ai_dashboard.sources.base import SourceAdapter, SourceRateLimited
from ai_dashboard.storage.db import Database


NewItemsCallback = Callable[[int, str], Awaitable[None]]


class PollingOrchestrator:
    def __init__(
        self,
        adapter_specs: list[tuple[str, dict[str, Any]]],
        db: Database,
        on_new_items: NewItemsCallback,
    ) -> None:
        self.adapter_specs = adapter_specs
        self.db = db
        self.on_new_items = on_new_items
        self._adapters: list[SourceAdapter] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._wake_events: dict[str, asyncio.Event] = {}
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        from ai_dashboard.sources import build_adapter

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

        for kind, options in self.adapter_specs:
            adapter = build_adapter(kind, http=self._http, options=options)
            self._adapters.append(adapter)

        for adapter in self._adapters:
            ev = asyncio.Event()
            ev.set()
            self._wake_events[adapter.kind] = ev
            task = asyncio.create_task(
                self._run_adapter(adapter, ev), name=f"poll-{adapter.kind}"
            )
            self._tasks.append(task)

    async def _run_adapter(self, adapter: Any, wake: asyncio.Event) -> None:
        sleep_seconds: float = 0.0
        while True:
            if sleep_seconds > 0:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=sleep_seconds)
                    wake.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                wake.clear()

            try:
                items = await adapter.fetch()
                new_count = await self.db.upsert_items(items)
                await self.db.set_last_poll_time(datetime.now(timezone.utc))
                await self.on_new_items(new_count, adapter.kind)
                await self.db.update_source_state(
                    adapter.kind,
                    last_fetched=datetime.now(timezone.utc),
                    consecutive_failures=0,
                )
                sleep_seconds = float(adapter.default_interval_seconds)
            except asyncio.CancelledError:
                raise
            except SourceRateLimited:
                sleep_seconds = float(adapter.default_interval_seconds) * 2
            except Exception:  # SourceError is handled the same way here.
                state = await self.db.get_source_state(adapter.kind) or {}
                failures = int(state.get("consecutive_failures") or 0) + 1
                await self.db.update_source_state(
                    adapter.kind,
                    consecutive_failures=failures,
                )
                sleep_seconds = float(adapter.default_interval_seconds) * (
                    2 if failures >= 5 else 1
                )

    async def stop(self, timeout: float = 2.0) -> None:
        for task in self._tasks:
            task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout / 2,
            )
        except asyncio.TimeoutError:
            pass

        if self._http is not None:
            try:
                await asyncio.wait_for(self._http.aclose(), timeout=timeout / 2)
            except asyncio.TimeoutError:
                pass
            self._http = None

        self._tasks.clear()
        self._wake_events.clear()

    async def refresh_all_now(self) -> None:
        for ev in self._wake_events.values():
            ev.set()
