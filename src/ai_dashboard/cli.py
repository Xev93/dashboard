from __future__ import annotations

import argparse
import asyncio
import os
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path

from ai_dashboard.config import AppConfig
from ai_dashboard.daemon import DATA_DIR, LOG_PATH, PID_PATH, run_daemon

DAEMON_IDENTITY = "ai-dashboard-daemon"
LAUNCHD_LABEL = "com.ai-dashboard.daemon"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _read_pid_file() -> tuple[int, str] | None:
    try:
        lines = PID_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError:
        return None

    if len(lines) < 2:
        return None

    try:
        pid = int(lines[0].strip())
    except ValueError:
        return None

    return pid, lines[1].strip()


def _remove_pid_file() -> None:
    PID_PATH.unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _status_from_pid_file() -> tuple[bool, int | None]:
    pid_info = _read_pid_file()
    if pid_info is None:
        if PID_PATH.exists():
            _remove_pid_file()
        return False, None

    pid, identity = pid_info
    if identity != DAEMON_IDENTITY:
        _remove_pid_file()
        return False, None

    if _is_process_alive(pid):
        return True, pid

    _remove_pid_file()
    return False, None


def cmd_daemon_start(_args: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "ai_dashboard.cli", "daemon", "run"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    print("Daemon started")
    return 0


def cmd_daemon_run(_args: argparse.Namespace) -> int:
    config = AppConfig.load()
    return asyncio.run(run_daemon(config, foreground=True))


def cmd_daemon_stop(_args: argparse.Namespace) -> int:
    pid_info = _read_pid_file()
    if pid_info is None:
        if PID_PATH.exists():
            _remove_pid_file()
        print("stopped")
        return 0

    pid, identity = pid_info
    if identity != DAEMON_IDENTITY:
        print("stopped")
        _remove_pid_file()
        return 0

    if not _is_process_alive(pid):
        print("stopped")
        _remove_pid_file()
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_file()
        print("stopped")
        return 0
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            _remove_pid_file()
            print("stopped")
            return 0
        time.sleep(0.5)

    if not _is_process_alive(pid):
        _remove_pid_file()
        print("stopped")
        return 0

    print("warning: daemon still alive after 5s")
    return 1


def cmd_daemon_status(_args: argparse.Namespace) -> int:
    running, pid = _status_from_pid_file()
    if running and pid is not None:
        print(f"running (pid {pid})")
    else:
        print("stopped")
    return 0


def cmd_daemon_install(_args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print(
            "Error: daemon install/uninstall requires macOS (launchd). For Linux, use systemd manually.",
            file=sys.stderr,
        )
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_data = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "ai_dashboard.cli",
            "daemon",
            "run",
        ],
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    with LAUNCHD_PLIST_PATH.open("wb") as plist_file:
        plistlib.dump(plist_data, plist_file)
    result = subprocess.run(["launchctl", "load", "-w", str(LAUNCHD_PLIST_PATH)])
    return result.returncode


def cmd_daemon_uninstall(_args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        print(
            "Error: daemon install/uninstall requires macOS (launchd). For Linux, use systemd manually.",
            file=sys.stderr,
        )
        return 1
    result = subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_PATH)])
    LAUNCHD_PLIST_PATH.unlink(missing_ok=True)
    return result.returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-dashboard")
    subparsers = parser.add_subparsers(dest="command")

    daemon_parser = subparsers.add_parser("daemon")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command")

    daemon_start = daemon_subparsers.add_parser("start")
    daemon_start.set_defaults(func=cmd_daemon_start)

    daemon_run = daemon_subparsers.add_parser("run")
    daemon_run.set_defaults(func=cmd_daemon_run)

    daemon_stop = daemon_subparsers.add_parser("stop")
    daemon_stop.set_defaults(func=cmd_daemon_stop)

    daemon_status = daemon_subparsers.add_parser("status")
    daemon_status.set_defaults(func=cmd_daemon_status)

    daemon_install = daemon_subparsers.add_parser("install")
    daemon_install.set_defaults(func=cmd_daemon_install)

    daemon_uninstall = daemon_subparsers.add_parser("uninstall")
    daemon_uninstall.set_defaults(func=cmd_daemon_uninstall)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        from ai_dashboard.app import main as app_main

        return app_main()

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
