from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from ai_dashboard.config import AppConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.workers import PollingOrchestrator

DATA_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "ai-dashboard"
)
PID_PATH = DATA_DIR / "daemon.pid"
LOG_PATH = DATA_DIR / "daemon.log"

_LOG = logging.getLogger(__name__)
_FOREGROUND_LOGGING = False


async def run_daemon(config: AppConfig, *, foreground: bool = False) -> int:
    global _FOREGROUND_LOGGING

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _FOREGROUND_LOGGING = foreground
    _setup_logging(LOG_PATH, config.log_level)
    _write_pid(PID_PATH)

    db = Database(config.db_path)
    orchestrator: PollingOrchestrator | None = None
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals: list[signal.Signals] = []

    def _request_shutdown() -> None:
        _LOG.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: shutdown_event.set())
        handled_signals.append(sig)

    try:
        await db.connect()
        await db.init_schema()
        adapter_specs = [
            (source.kind, source.options) for source in config.sources if source.enabled
        ]
        orchestrator = PollingOrchestrator(
            adapter_specs=adapter_specs,
            db=db,
            on_new_items=_log_new_items,
        )
        await orchestrator.start()
        _LOG.info("Daemon started with %d source(s)", len(adapter_specs))
        await shutdown_event.wait()
        return 0
    finally:
        for sig in handled_signals:
            try:
                loop.remove_signal_handler(sig)
            except NotImplementedError:
                signal.signal(sig, signal.SIG_DFL)
        if orchestrator is not None:
            await orchestrator.stop(timeout=2.0)
        await db.close()
        _remove_pid(PID_PATH)


def _write_pid(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\nai-dashboard-daemon\n", encoding="utf-8")


def _remove_pid(pid_path: Path) -> None:
    pid_path.unlink(missing_ok=True)


def _setup_logging(log_path: Path, level: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_path)]
    if _FOREGROUND_LOGGING:
        handlers.append(logging.StreamHandler(sys.stderr))
    else:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


async def _log_new_items(count: int, kind: str) -> None:
    _LOG.info("Fetched %d new items from %s", count, kind)
