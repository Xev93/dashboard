from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from unittest.mock import Mock

from ai_dashboard import cli


def test_cli_default_no_args() -> None:
    parser = cli._build_parser()

    args = parser.parse_args([])

    assert args.command is None


def test_daemon_status_no_pid_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "PID_PATH", tmp_path / "daemon.pid")

    result = cli.cmd_daemon_status(Mock())

    assert result == 0
    assert capsys.readouterr().out.strip() == "stopped"


def test_daemon_status_running(tmp_path: Path, monkeypatch, capsys) -> None:
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    pid_path.write_text(f"{cli.os.getpid()}\n{cli.DAEMON_IDENTITY}\n", encoding="utf-8")

    result = cli.cmd_daemon_status(Mock())

    assert result == 0
    assert capsys.readouterr().out.strip() == f"running (pid {cli.os.getpid()})"


def test_daemon_status_stale_pid(tmp_path: Path, monkeypatch, capsys) -> None:
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    pid_path.write_text("99999999\nai-dashboard-daemon\n", encoding="utf-8")

    result = cli.cmd_daemon_status(Mock())

    assert result == 0
    assert capsys.readouterr().out.strip() == "stopped"
    assert not pid_path.exists()


def test_daemon_status_wrong_identity(tmp_path: Path, monkeypatch, capsys) -> None:
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    pid_path.write_text(f"{cli.os.getpid()}\nwrong-daemon\n", encoding="utf-8")

    result = cli.cmd_daemon_status(Mock())

    assert result == 0
    assert capsys.readouterr().out.strip() == "stopped"
    assert not pid_path.exists()


def test_daemon_stop_no_process(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "PID_PATH", tmp_path / "daemon.pid")

    result = cli.cmd_daemon_stop(Mock())

    assert result == 0
    assert capsys.readouterr().out.strip() == "stopped"


def test_daemon_install_creates_plist(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    log_path = data_dir / "daemon.log"
    plist_path = tmp_path / "LaunchAgents" / "com.ai-dashboard.daemon.plist"
    run_mock = Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))

    monkeypatch.setattr(cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(cli, "LOG_PATH", log_path)
    monkeypatch.setattr(cli, "LAUNCHD_PLIST_PATH", plist_path)
    monkeypatch.setattr(cli.subprocess, "run", run_mock)

    result = cli.cmd_daemon_install(Mock())

    assert result == 0
    assert plist_path.exists()
    with plist_path.open("rb") as plist_file:
        plist_data = plistlib.load(plist_file)
    assert plist_data["KeepAlive"] is True
    assert plist_data["ProgramArguments"][2:] == ["ai_dashboard.cli", "daemon", "run"]
    assert plist_data["StandardOutPath"] == str(log_path)
    assert plist_data["StandardErrorPath"] == str(log_path)
    run_mock.assert_called_once_with(["launchctl", "load", "-w", str(plist_path)])


def test_daemon_uninstall_removes_plist(tmp_path: Path, monkeypatch) -> None:
    plist_path = tmp_path / "LaunchAgents" / "com.ai-dashboard.daemon.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(b"plist")
    run_mock = Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))

    monkeypatch.setattr(cli, "LAUNCHD_PLIST_PATH", plist_path)
    monkeypatch.setattr(cli.subprocess, "run", run_mock)

    result = cli.cmd_daemon_uninstall(Mock())

    assert result == 0
    assert not plist_path.exists()
    run_mock.assert_called_once_with(["launchctl", "unload", str(plist_path)])
