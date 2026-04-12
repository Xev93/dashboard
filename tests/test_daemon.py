from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from ai_dashboard.config import AppConfig, SourceConfig
from ai_dashboard import daemon


def test_write_pid_creates_file(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"

    daemon._write_pid(pid_path)

    assert pid_path.exists()
    assert "ai-dashboard-daemon" in pid_path.read_text(encoding="utf-8")


def test_write_pid_content_format(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"

    daemon._write_pid(pid_path)

    assert pid_path.read_text(encoding="utf-8") == (
        f"{daemon.os.getpid()}\nai-dashboard-daemon\n"
    )


def test_remove_pid_cleans_up(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123\nai-dashboard-daemon\n", encoding="utf-8")

    daemon._remove_pid(pid_path)

    assert not pid_path.exists()


def test_remove_pid_missing_ok(tmp_path: Path) -> None:
    daemon._remove_pid(tmp_path / "missing.pid")


def test_setup_logging_creates_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "daemon.log"

    daemon._setup_logging(log_path, "INFO", False)

    file_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.FileHandler)
    ]

    assert log_path.exists()
    assert any(Path(handler.baseFilename) == log_path for handler in file_handlers)

    logging.shutdown()


@pytest.mark.asyncio
async def test_log_new_items() -> None:
    await daemon._log_new_items(2, "arxiv")


@pytest.mark.asyncio
async def test_run_daemon_writes_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "daemon.log"
    db_path = tmp_path / "cache.db"
    created_pid_contents: list[str] = []

    monkeypatch.setattr(daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)

    class ImmediateShutdownEvent:
        def set(self) -> None:
            return None

        async def wait(self) -> None:
            return None

    class FakeOrchestrator:
        def __init__(self, adapter_specs, db, on_new_items) -> None:
            self.adapter_specs = adapter_specs
            self.db = db
            self.on_new_items = on_new_items

        async def start(self) -> None:
            created_pid_contents.append(pid_path.read_text(encoding="utf-8"))

        async def stop(self, timeout: float = 2.0) -> None:
            return None

    monkeypatch.setattr(daemon.asyncio, "Event", ImmediateShutdownEvent)
    monkeypatch.setattr(daemon, "PollingOrchestrator", FakeOrchestrator)

    config = AppConfig(
        sources=[SourceConfig(kind="arxiv", enabled=True, options={})],
        db_path=db_path,
    )

    result = await daemon.run_daemon(config)

    assert result == 0
    assert created_pid_contents == [f"{daemon.os.getpid()}\nai-dashboard-daemon\n"]


@pytest.mark.asyncio
async def test_run_daemon_removes_pid_on_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "daemon.log"
    db_path = tmp_path / "cache.db"

    monkeypatch.setattr(daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)

    class ImmediateShutdownEvent:
        def set(self) -> None:
            return None

        async def wait(self) -> None:
            return None

    class FakeOrchestrator:
        async def start(self) -> None:
            return None

        async def stop(self, timeout: float = 2.0) -> None:
            return None

    monkeypatch.setattr(daemon.asyncio, "Event", ImmediateShutdownEvent)
    monkeypatch.setattr(
        daemon, "PollingOrchestrator", lambda *args, **kwargs: FakeOrchestrator()
    )

    config = AppConfig(
        sources=[SourceConfig(kind="arxiv", enabled=True, options={})],
        db_path=db_path,
    )

    result = await daemon.run_daemon(config)

    assert result == 0
    assert not pid_path.exists()


@pytest.mark.asyncio
async def test_run_daemon_uses_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "daemon.log"
    db_path = tmp_path / "cache.db"
    state: dict[str, object] = {}

    monkeypatch.setattr(daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)

    class ImmediateShutdownEvent:
        def set(self) -> None:
            return None

        async def wait(self) -> None:
            return None

    class FakeOrchestrator:
        def __init__(self, adapter_specs, db, on_new_items) -> None:
            state["adapter_specs"] = adapter_specs
            state["db"] = db
            state["on_new_items"] = on_new_items
            state["start_called"] = False
            state["stop_called"] = False
            state["stop_timeout"] = None

        async def start(self) -> None:
            state["start_called"] = True

        async def stop(self, timeout: float = 2.0) -> None:
            state["stop_called"] = True
            state["stop_timeout"] = timeout

    monkeypatch.setattr(daemon.asyncio, "Event", ImmediateShutdownEvent)
    monkeypatch.setattr(daemon, "PollingOrchestrator", FakeOrchestrator)

    config = AppConfig(
        sources=[
            SourceConfig(kind="arxiv", enabled=True, options={"topic": "ai"}),
            SourceConfig(kind="hn", enabled=False, options={}),
        ],
        db_path=db_path,
    )

    result = await daemon.run_daemon(config)

    assert result == 0
    assert state["adapter_specs"] == [("arxiv", {"topic": "ai"})]
    assert state["start_called"] is True
    assert state["stop_called"] is True
    assert state["stop_timeout"] == 2.0
    assert state["on_new_items"] is daemon._log_new_items
