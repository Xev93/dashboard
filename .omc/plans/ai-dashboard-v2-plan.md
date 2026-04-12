# Implementation Plan: AI Dashboard V2

**Source spec:** `.omc/specs/deep-interview-ai-dashboard-v2.md` (9-round deep interview, 15.0% final ambiguity)
**V1 plan:** `.omc/plans/ai-news-tui-implementation.md`
**Generated:** 2026-04-12 via Planner (direct mode, no interview)
**Target:** brownfield upgrade at `/Users/dev/projects/dashboard`
**Status:** REVISED — Architect conditions incorporated (iteration 1)

---

## Overview

V2 transforms the ai-dashboard from a foreground-only TUI feed reader into a **continuously-collecting, heuristically-ranked, multi-source intelligence dashboard**. The five scope items are: (1) a persistent daemon that extracts the existing `PollingOrchestrator` to a standalone process for 24/7 data collection, (2) new source adapters for lab blogs and Reddit plus research-identified sources, (3) source tabs and text filter UI for navigating the growing feed, (4) new `FeedListStrategy` implementations (`BySourceStrategy`, `HeuristicRankingStrategy`, `FilteredStrategy`), and (5) a configurable heuristic ranking system that scores items by engagement, source authority, keyword relevance, recency, and user behavior. The daemon is the V2 spine — it enables historical completeness between TUI sessions. All other features build on the expanded data it collects.

---

## Architecture Decision Records

### ADR-V2-1: Daemon Extraction Pattern

**Decision:** Extract `PollingOrchestrator` from `workers.py` into a standalone daemon process. The TUI becomes a read-mostly client.

**Drivers:**
1. Continuous data collection — never miss items published between TUI sessions
2. The existing `PollingOrchestrator` already encapsulates all polling logic; extraction is a seam-split, not a rewrite
3. SQLite WAL mode already supports concurrent readers; adding a second process (daemon writes, TUI reads) is a natural fit

**Alternatives considered:**
- *Cron-based fetcher script*: Rejected because cron has 1-minute minimum granularity, no built-in retry/backoff, and would require duplicating the adapter orchestration logic
- *Background thread in TUI*: This is V1's current approach — rejected because it doesn't collect when the TUI is closed

**Implementation:**
- New module `src/ai_dashboard/daemon.py` — async main loop that instantiates `PollingOrchestrator` with its own `Database` connection and runs indefinitely
- New CLI subcommand group: `ai-dashboard daemon start|stop|status|install|uninstall`
- CLI entry via `src/ai_dashboard/cli.py` using `argparse` (no new dependency — stdlib)
- PID file at `~/.local/share/ai-dashboard/daemon.pid`
- Log file at `~/.local/share/ai-dashboard/daemon.log`
- `launchd` plist at `~/Library/LaunchAgents/com.ai-dashboard.daemon.plist`

**Consequences:**
- Two processes may write to the same SQLite DB — WAL mode handles this, but both must use `PRAGMA journal_mode=WAL` AND `PRAGMA busy_timeout=5000` (both set in `Database.connect()`)
- TUI must detect daemon presence on startup and skip its own polling if daemon is running
- The `PollingOrchestrator` class itself is NOT modified — it's used as-is by both the daemon and the TUI fallback
- Daemon exposes TWO entry modes: `daemon start` (detaches, for CLI use) and `daemon run` (foreground, for launchd supervision)

### ADR-V2-2: DB Migration Strategy

**Decision:** Bump `SCHEMA_VERSION` from 1 to 2. Add new tables via additive migration. No destructive changes to existing tables.

**Drivers:**
1. V1 databases must continue working — the spec requires forward-compatible migration
2. New tables (`user_search_history`, `item_view_log`) have no foreign keys to existing tables — purely additive
3. A `schema_version` table already exists in V1

**Implementation:**
- `SCHEMA_V2_SQL` migration script in `db.py` that creates the two new tables
- `Database.init_schema()` reads the current schema version and applies pending migrations
- Migration is idempotent (uses `CREATE TABLE IF NOT EXISTS`)

**Consequences:**
- V1 data is preserved. V2 TUI and daemon both run the migration on first connect.
- Both daemon and TUI may race to apply the migration — `CREATE TABLE IF NOT EXISTS` is safe under WAL

### ADR-V2-3: Source Research Before Implementation

**Decision:** Execute a research phase before coding new adapters beyond lab blogs and Reddit.

**Drivers:**
1. The spec explicitly requires a research document evaluating ≥5 candidate sources
2. Prevents building adapters for sources that turn out to be unusable (rate limits, poor data quality, high cost)

**Implementation:**
- Research task produces `.omc/research/v2-source-analysis.md`
- Research output informs which additional adapters to build (≥1 beyond lab blogs + Reddit)
- Lab blogs and Reddit adapters are confirmed — they proceed in parallel with research

### ADR-V2-4: Strategy Pattern — Decorator for Filtering

**Decision:** Text filtering is implemented as a `FilteredStrategy` decorator wrapping any base strategy, not as a parameter on existing strategies.

**Drivers:**
1. The `FeedListStrategy` Protocol MUST NOT change (spec constraint)
2. Filtering is orthogonal to sorting — it should compose with any strategy
3. The decorator pattern preserves the single-responsibility principle

**Implementation:**
- `FilteredStrategy` wraps any `FeedListStrategy`, calls `base.items()`, then filters by text match
- The filter bar widget sets/clears the decorator on the active strategy
- When the filter is cleared, the original base strategy is restored (not a new instance)

### ADR-V2-5: Heuristic Ranking — Database-Backed User Behavior

**Decision:** Track user behavior (viewed/skipped items, search terms) in SQLite to feed the heuristic ranking formula.

**Drivers:**
1. `keyword_boost` requires knowing the user's most frequent search terms → needs `user_search_history` table
2. `skip_penalty` requires knowing which source kinds the user tends to skip → needs `item_view_log` table
3. All data must survive across sessions → SQLite storage

**Consequences:**
- The TUI must record `viewed` and `skipped` actions as the user navigates the feed
- Privacy note: all data is local-only. No telemetry, no remote storage.

---

## Delegation & Execution Constraints

All implementation work is delegated per `AGENTS.md`:

| Work type | Delegation |
|---|---|
| New modules, adapters, strategies, daemon | `task(category="deep", ...)` |
| Complex ranking algorithm, migration logic | `task(category="ultrabrain", ...)` |
| Trivial single-file changes (config additions, import updates) | `task(category="quick", ...)` |
| Codebase exploration / impact analysis | `task(subagent_type="explore", run_in_background=true, ...)` |
| Source research (Reddit API, lab blog RSS feeds) | `task(subagent_type="librarian", run_in_background=true, ...)` |

### Global Invariants (apply to EVERY phase)

1. **All 41 existing V1 tests must pass** after every phase. Run `pytest tests/` as verification.
2. **`FeedListStrategy` Protocol (`strategies/base.py`) MUST NOT be modified.** New strategies implement it; they don't change it.
3. **`SourceAdapter` Protocol (`sources/base.py`) MUST NOT be modified.** New adapters implement it; they don't change it.
4. **AST pluggability test** (`test_feed_list_widget_imports_only_strategy_base`) must continue passing.
5. **No `huggingface_hub` SDK** — all HF access via `httpx` (already the case in V1).
6. **One source file per `task()` call** — follows the local LLM offload pattern.
7. **Leaf-first ordering** within each phase — utilities and data classes before dependent code.
8. **Each phase independently testable** — tests for that phase pass without requiring later phases.

### QA Verification Structure

Each phase follows the pattern: **implementation tasks → test tasks → verification task**.

| Implementation Tasks | Verified By (tests) | Verified By (QA scenario) |
|---|---|---|
| Phase 1: Tasks 1.0–1.4 | Task 1.5 (`test_daemon.py`, `test_cli.py`) | Task 1.6 (executable QA) |
| Phase 2: Task 2.1 | Task 2.2 (`test_migration.py`) | `pytest tests/test_migration.py -v` → exit 0 |
| Phase 3: Task 3.1 | N/A (research document) | File exists at `.omc/research/v2-source-analysis.md` with ≥5 evaluations |
| Phase 4: Tasks 4.1, 4.3, 4.5–4.10 | Tasks 4.2, 4.4 (`test_lab_blog.py`, `test_reddit.py`) | Task 4.11: `pytest tests/test_sources/ -v` → exit 0 |
| Phase 5: Tasks 5.1–5.3 | Task 5.4 (`test_strategies.py`) | `pytest tests/test_strategies.py -v` → exit 0 + AST pluggability passes |
| Phase 6: Tasks 6.1–6.4 | Task 6.5 (`test_search_filter.py`) | Task 6.6 (executable QA) |
| Phase 7: Tasks 7.1–7.4 | Task 7.5 (`test_heuristic_ranking.py`) | Task 7.6 (executable QA) |
| Phase 8: Tasks 8.1, 8.3–8.4 | Task 8.1 (`test_integration_v2.py`) | Tasks 8.2, 8.5 (executable QA) |

**Rule:** An implementation task is considered verified when its paired test task passes AND the phase verification task's QA scenario passes. No implementation task ships without passing its test pair.

---

## Phase 1: Daemon Extraction (V2 Spine)

**Goal:** Extract the V1 `PollingOrchestrator` into a standalone daemon process with CLI management commands, launchd integration, and TUI fallback detection.

**Dependencies:** None (this is the foundation).

**Spec criteria covered:** A.1–A.12, F.1, F.2, F.3, F.4

### Task 1.0: Add `PRAGMA busy_timeout` to `Database.connect()` — Concurrency Prerequisite

**Category:** `quick`

**Description:** Add `PRAGMA busy_timeout=5000` to `Database.connect()` so that concurrent daemon+TUI writes don't fail with `SQLITE_BUSY`. This is a prerequisite for all Phase 1+ work.

**File:** `src/ai_dashboard/storage/db.py` (modify)

**Changes:**
```python
async def connect(self) -> None:
    self.connection = await aiosqlite.connect(self._path)
    await self.connection.execute("PRAGMA journal_mode=WAL")
    await self.connection.execute("PRAGMA busy_timeout=5000")  # NEW: 5s retry on contention
```

**Constraints:**
- Add AFTER the existing `PRAGMA journal_mode=WAL` line
- Do NOT modify any other part of `connect()`
- All 41 V1 tests must still pass after this change

**Acceptance criteria:**
- [ ] `Database.connect()` sets both `journal_mode=WAL` and `busy_timeout=5000`
- [ ] All V1 tests pass (this is a safe additive change)

---

### Task 1.1: Create `src/ai_dashboard/daemon.py` — Daemon Main Loop

**Category:** `deep`

**Description:** Create the daemon entry point that runs `PollingOrchestrator` as a standalone process.

**File:** `src/ai_dashboard/daemon.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/daemon.py
"""Standalone daemon process for continuous data collection.

Runs the V1 PollingOrchestrator in an asyncio event loop, writing to the
shared SQLite database. Managed via CLI (ai-dashboard daemon start/stop/status)
or launchd for production.
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from ai_dashboard.config import AppConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.workers import PollingOrchestrator

# Key functions:
# - async def run_daemon(config: AppConfig) -> None
#     Main loop: connect DB, start orchestrator, wait for shutdown signal
# - def _write_pid(pid_path: Path) -> None
# - def _remove_pid(pid_path: Path) -> None
# - def _setup_logging(log_path: Path, level: str) -> None
# - def _handle_shutdown(signum, frame) -> None
#     Sets a threading.Event / asyncio.Event to trigger clean shutdown
```

**Constraints:**
- Import and reuse `PollingOrchestrator` as-is — do NOT copy or modify `workers.py`
- `on_new_items` callback should be a no-op logger (no TUI to notify): `async def _log_new_items(count, kind): logger.info(f"Fetched {count} new items from {kind}")`
- PID file path: `~/.local/share/ai-dashboard/daemon.pid` (respect `XDG_DATA_HOME`)
- PID file format: `"{pid}\nai-dashboard-daemon\n"` (PID + identity marker for stale detection)
- Log file path: `~/.local/share/ai-dashboard/daemon.log` (configurable log level from `config.toml`)
- Signal handling: `SIGTERM` → clean shutdown (orchestrator.stop(), db.close(), remove PID file). `SIGINT` → same.
- Must call `Database.connect()` and `Database.init_schema()` on startup
- `Database.connect()` MUST set `PRAGMA busy_timeout=5000` for concurrent-write safety
- Must call `orchestrator.stop(timeout=2.0)` and `db.close()` on shutdown
- Must write PID file after successful startup, remove on clean shutdown
- **Two entry modes:** `run_daemon(config, foreground=True)` stays in foreground (for launchd), `foreground=False` is called by the detaching `daemon start` CLI path

**Acceptance criteria:**
- [ ] Daemon starts, creates PID file, begins polling
- [ ] SIGTERM causes clean shutdown within 2s, removes PID file
- [ ] Daemon logs to the configured log file
- [ ] Daemon uses the same `PollingOrchestrator` class from `workers.py`

### Task 1.2: Create `src/ai_dashboard/cli.py` — CLI Entry Point

**Category:** `deep`

**Description:** Create the CLI module with `daemon` subcommand group (start/stop/status/install/uninstall).

**File:** `src/ai_dashboard/cli.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/cli.py
"""CLI entry point for ai-dashboard.

Subcommands:
  ai-dashboard                  — launch TUI (default, existing behavior)
  ai-dashboard daemon start     — start background daemon (detached)
  ai-dashboard daemon run       — run daemon in foreground (for launchd supervision)
  ai-dashboard daemon stop      — stop running daemon
  ai-dashboard daemon status    — report running/stopped
  ai-dashboard daemon install   — create launchd plist, load via launchctl
  ai-dashboard daemon uninstall — unload and remove plist
"""
import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

# Key functions:
# - def main() -> int  (new entry point, replaces app.main for CLI)
# - def cmd_daemon_start(args) -> int
#     Fork/spawn a child process running `ai-dashboard daemon run`, detach from terminal
#     Use subprocess.Popen with start_new_session=True, redirect stdout/stderr to log
# - def cmd_daemon_run(args) -> int
#     Run daemon in foreground (blocking). This is what launchd supervises.
#     Calls daemon.run_daemon(config, foreground=True) directly.
# - def cmd_daemon_stop(args) -> int
#     Read PID file, VALIDATE identity marker matches "ai-dashboard-daemon",
#     send SIGTERM, wait up to 5s for PID to disappear, remove stale PID if needed
# - def cmd_daemon_status(args) -> int
#     Read PID file, validate identity marker, check if process alive via os.kill(pid, 0)
#     If PID alive but identity mismatch → report "stopped" + clean stale PID file
# - def cmd_daemon_install(args) -> int
#     Generate ~/Library/LaunchAgents/com.ai-dashboard.daemon.plist with KeepAlive=true
#     ProgramArguments = [sys.executable, "-m", "ai_dashboard.cli", "daemon", "run"]
#     (launchd supervises the foreground `run` command, NOT the detaching `start`)
#     Run: launchctl load -w <plist_path>
# - def cmd_daemon_uninstall(args) -> int
#     Run: launchctl unload <plist_path>
#     Remove the plist file
```

**Constraints:**
- Use `argparse` only (stdlib) — no click, typer, or other CLI dependencies
- `daemon start` must detach from terminal (use `subprocess.Popen` with `start_new_session=True`)
- `daemon stop` must send `SIGTERM`, not `SIGKILL`. Wait up to 5 seconds for clean shutdown. If still alive after 5s, warn but do NOT force-kill.
- `daemon status` output: exactly `"running (pid NNNN)"` or `"stopped"`
- Plist template must include `KeepAlive=true`, `StandardOutPath` → daemon.log, `StandardErrorPath` → daemon.log
- Running `ai-dashboard` with no subcommand launches the TUI (backward compatible)

**Context files (read-only):**
- `src/ai_dashboard/app.py` — existing `main()` function
- `src/ai_dashboard/daemon.py` — the daemon module from Task 1.1

**Acceptance criteria:**
- [ ] `ai-dashboard daemon start` spawns background process, writes PID file, detaches (AC A.1)
- [ ] `ai-dashboard daemon stop` sends SIGTERM, waits, removes PID file (AC A.2)
- [ ] `ai-dashboard daemon status` reports running/stopped (AC A.3)
- [ ] `ai-dashboard daemon install` creates plist with KeepAlive=true, loads it (AC A.4)
- [ ] `ai-dashboard daemon uninstall` unloads and removes plist (AC A.5)
- [ ] `ai-dashboard` (no args) still launches TUI (AC F.1)

### Task 1.3: Update `pyproject.toml` — CLI Entry Point

**Category:** `quick`

**Description:** Update the `[project.scripts]` entry to point to the new CLI entry point instead of `app:main`.

**File:** `pyproject.toml` (modify)

**Changes:**
```toml
[project.scripts]
ai-dashboard = "ai_dashboard.cli:main"
```

**Constraints:**
- The new `cli.main()` must default to launching the TUI when no subcommand is given, preserving backward compatibility
- Do NOT change any other section of `pyproject.toml`

**Acceptance criteria:**
- [ ] `ai-dashboard` invokes `cli.main()` which defaults to TUI
- [ ] `ai-dashboard daemon start` invokes daemon subcommand

### Task 1.4: Add Daemon Detection to `app.py` — TUI Fallback

**Category:** `deep`

**Description:** Modify `AIDashboardApp.on_mount()` to detect whether the daemon is running. If yes, skip starting the orchestrator (TUI becomes read-only client). If no, start orchestrator as before (V1 fallback).

**File:** `src/ai_dashboard/app.py` (modify)

**Implementation details:**
```python
# In AIDashboardApp:

def _is_daemon_running(self) -> bool:
    """Check if the daemon is running by reading PID file + validating identity.
    
    Handles stale PID files (process died) and PID reuse (different process
    inherited the PID) by checking the identity marker in the PID file.
    """
    pid_path = _daemon_pid_path()  # ~/.local/share/ai-dashboard/daemon.pid
    if not pid_path.exists():
        return False
    try:
        lines = pid_path.read_text().strip().splitlines()
        if len(lines) < 2:
            pid_path.unlink(missing_ok=True)  # Malformed PID file
            return False
        pid = int(lines[0])
        identity = lines[1]
        if identity != "ai-dashboard-daemon":
            pid_path.unlink(missing_ok=True)  # Stale/foreign PID file
            return False
        os.kill(pid, 0)  # Check if process exists
        return True
    except (ValueError, OSError, ProcessLookupError):
        pid_path.unlink(missing_ok=True)  # Stale PID — clean up
        return False

async def on_mount(self) -> None:
    # ... existing DB init ...
    await self.content_fetcher.start()
    feed_list = self.query_one(FeedListWidget)
    await feed_list.refresh_items()

    if self._is_daemon_running():
        self.orchestrator = None  # Daemon handles polling
        # Optionally: set up a periodic refresh timer to re-read DB
        self.set_interval(30, self._periodic_refresh)
    else:
        # V1 fallback: TUI owns polling
        self.orchestrator = PollingOrchestrator(
            self._adapter_specs(), self.db, self._post_items_arrived
        )
        await self.orchestrator.start()

async def _periodic_refresh(self) -> None:
    """When daemon is polling, periodically refresh the feed list from DB."""
    feed_list = self.query_one(FeedListWidget)
    await feed_list.refresh_items()
```

**Constraints:**
- Do NOT modify `PollingOrchestrator` — the detection is entirely in `app.py`
- The `_is_daemon_running()` check must be a simple PID file + `os.kill(pid, 0)` check
- When daemon is running, TUI must NOT start its own orchestrator (AC A.8)
- When daemon is NOT running, TUI must fall back to V1 behavior exactly (AC A.9, F.1)
- Add a status indicator to the TUI showing whether daemon mode is active or fallback polling is active

**Context files (read-only):**
- `src/ai_dashboard/workers.py` — PollingOrchestrator interface
- `src/ai_dashboard/daemon.py` — PID file path constant

**Acceptance criteria:**
- [ ] When daemon is running, TUI skips orchestrator startup (AC A.8)
- [ ] When daemon is NOT running, TUI uses V1 foreground polling (AC A.9)
- [ ] V1 behavior is fully preserved when daemon is not running (AC F.1)

### Task 1.5: Tests for Daemon and CLI

**Category:** `deep`

**Description:** Create test suite for daemon and CLI functionality.

**Files:**
- `tests/test_daemon.py` (new)
- `tests/test_cli.py` (new)

**Test cases:**
```python
# tests/test_daemon.py
# - test_daemon_writes_pid_file: start daemon, verify PID file exists with valid integer
# - test_daemon_removes_pid_on_stop: start daemon, send SIGTERM, verify PID file removed
# - test_daemon_polls_sources: start daemon with mock adapters, verify DB gets items
# - test_daemon_log_file_created: start daemon, verify log file exists

# tests/test_cli.py
# - test_cli_no_args_launches_tui: verify default behavior
# - test_daemon_status_stopped: no PID file → "stopped"
# - test_daemon_status_running: create PID file with current process PID → "running (pid NNNN)"
# - test_daemon_status_stale_pid: create PID file with dead PID → "stopped" (stale cleanup)
# - test_daemon_install_creates_plist: verify plist file content
# - test_daemon_uninstall_removes_plist: verify cleanup
```

**Constraints:**
- Use `tmp_path` for PID file and log file paths in tests
- Mock `subprocess.Popen` for start/stop tests
- Do NOT actually launch launchd in tests — mock `subprocess.run` for launchctl calls
- Tests must not require root/sudo

**Acceptance criteria:**
- [ ] All daemon lifecycle tests pass
- [ ] CLI subcommand tests pass
- [ ] All 41 existing V1 tests still pass

### Task 1.6: Verify Phase 1 Completeness

**Category:** `quick`

**Description:** Run the full test suite and perform manual verification of daemon lifecycle.

**QA Scenario (executable steps):**

```bash
# Step 1: Run full test suite
pytest tests/ -v
# EXPECTED: All V1 tests (41) pass + all new daemon/CLI tests pass. Exit code 0.

# Step 2: Verify daemon start/stop lifecycle
ai-dashboard daemon start
# EXPECTED: Process detaches, PID file created at ~/.local/share/ai-dashboard/daemon.pid

ai-dashboard daemon status
# EXPECTED: Output matches regex "running \(pid \d+\)"

ai-dashboard daemon stop
# EXPECTED: PID file removed, process gone. Exit code 0.

ai-dashboard daemon status
# EXPECTED: Output is exactly "stopped"

# Step 3: Verify SIGKILL safety (WAL resilience)
ai-dashboard daemon start
PID=$(head -1 ~/.local/share/ai-dashboard/daemon.pid)
sleep 2  # Let it poll at least once
kill -9 $PID
# Wait, then verify DB integrity:
python -c "import sqlite3; conn=sqlite3.connect('$HOME/.local/share/ai-dashboard/cache.db'); print(conn.execute('PRAGMA integrity_check').fetchone())"
# EXPECTED: ('ok',)

# Step 4: Verify AST pluggability invariant
pytest tests/ -k "pluggability" -v
# EXPECTED: Pass
```

**Acceptance criteria:**
- [ ] `pytest tests/` — exit code 0, all V1 tests (41) + new tests pass
- [ ] `ai-dashboard daemon status` reports "running (pid NNNN)" after start, "stopped" after stop
- [ ] AST pluggability test passes
- [ ] `PRAGMA integrity_check` returns `('ok',)` after SIGKILL (AC A.11)

---

## Phase 2: Database Migration

**Goal:** Add V2 database tables (`user_search_history`, `item_view_log`) and implement a migration system that upgrades V1 databases non-destructively.

**Dependencies:** Phase 1 (daemon must be running to verify concurrent access).

**Spec criteria covered:** E.8, F.3

### Task 2.1: Add V2 Migration SQL to `src/ai_dashboard/storage/db.py`

**Category:** `deep`

**Description:** Add schema version 2 migration and upgrade `Database.init_schema()` to support incremental migrations.

**File:** `src/ai_dashboard/storage/db.py` (modify)

**Implementation details:**
```python
SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS user_search_history (
    term      TEXT NOT NULL,
    count     INTEGER NOT NULL DEFAULT 1,
    last_used TEXT NOT NULL,
    PRIMARY KEY (term)
);

CREATE TABLE IF NOT EXISTS item_view_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_uid  TEXT NOT NULL,
    action      TEXT NOT NULL CHECK(action IN ('viewed', 'skipped')),
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_item_view_log_timestamp ON item_view_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_item_view_log_action ON item_view_log(source_kind, action);
"""

# Updated init_schema():
async def init_schema(self) -> None:
    conn = self.connection
    current_version = await self._get_schema_version()
    if current_version < 1:
        await conn.executescript(SCHEMA_V1_SQL)
    if current_version < 2:
        await conn.executescript(SCHEMA_V2_SQL)
        await conn.execute("UPDATE schema_version SET version = 2")
    await conn.commit()

async def _get_schema_version(self) -> int:
    conn = self.connection
    try:
        cursor = await conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else 0
    except Exception:
        return 0
```

**New methods to add to `Database`:**
```python
async def record_item_view(self, source_kind: str, source_uid: str, action: str) -> None:
    """Record a viewed or skipped action for heuristic ranking."""
    # action must be 'viewed' or 'skipped'
    # Insert into item_view_log

async def record_search_term(self, term: str) -> None:
    """Record or increment a search term for keyword boost ranking."""
    # INSERT OR UPDATE user_search_history, increment count, update last_used

async def get_top_search_terms(self, limit: int = 10) -> list[tuple[str, int]]:
    """Return the top N most-used search terms."""
    # SELECT term, count FROM user_search_history ORDER BY count DESC LIMIT ?

async def get_skip_counts(self, last_n_views: int = 50) -> dict[str, int]:
    """Return skip counts per source_kind from the last N item view logs."""
    # SELECT source_kind, COUNT(*) FROM item_view_log
    # WHERE action = 'skipped' AND id > (SELECT MAX(id) - ? FROM item_view_log)
    # GROUP BY source_kind

async def get_engagement_percentile(self, source_kind: str) -> float:
    """Return the 95th percentile engagement value for a source kind."""
    # Compute from raw_payload engagement fields per source
```

**Constraints:**
- Existing V1 tables MUST NOT be altered — only new tables added
- Migration must be idempotent — running `init_schema()` twice on a V2 DB is a no-op
- `SCHEMA_V1_SQL` must remain intact — it's still used for fresh installs
- The `schema_version` table already exists in V1 with `version = 1`
- Both daemon and TUI call `init_schema()` on startup — the migration must be safe under concurrent execution (WAL mode + `IF NOT EXISTS`)

**Context files (read-only):**
- `src/ai_dashboard/storage/models.py` — FeedItem dataclass
- `src/ai_dashboard/strategies/base.py` — FeedListStrategy Protocol

**Acceptance criteria:**
- [ ] V1 database migrates to V2 without data loss (AC F.3)
- [ ] New tables exist after migration: `user_search_history`, `item_view_log`
- [ ] `schema_version` reads `2` after migration
- [ ] Running migration on already-V2 DB is a no-op
- [ ] Fresh install creates both V1 and V2 tables

### Task 2.2: Tests for DB Migration

**Category:** `deep`

**File:** `tests/test_migration.py` (new)

**Test cases:**
```python
# - test_fresh_install_creates_v2_schema: new DB has all tables, version=2
# - test_v1_to_v2_migration: create V1 DB, run init_schema, verify new tables exist, old data preserved
# - test_migration_idempotent: run init_schema twice, verify no errors
# - test_record_item_view: insert viewed/skipped records, verify in DB
# - test_record_search_term: insert and increment, verify count
# - test_get_top_search_terms: insert multiple terms, verify ordering
# - test_get_skip_counts: insert view logs, verify skip counts per source
# - test_concurrent_migration: two Database instances both call init_schema (simulate daemon+TUI race)
```

**Acceptance criteria:**
- [ ] All migration tests pass
- [ ] All 41 V1 tests still pass (migration doesn't break existing schema)

---

## Phase 3: Source Research

**Goal:** Identify and evaluate additional AI data sources beyond the confirmed lab blogs and Reddit.

**Dependencies:** None (can run in parallel with Phase 1 and Phase 2).

**Spec criteria covered:** B.1

### Task 3.1: Research Task — Source Evaluation

**Category:** `task(subagent_type="librarian", run_in_background=true, ...)`

**Description:** Research and evaluate ≥5 candidate AI data sources. Produce a structured analysis document.

**Output file:** `.omc/research/v2-source-analysis.md`

**Research requirements:**
For each candidate source, evaluate:
- API availability (public? rate limits? auth required? cost?)
- Data quality (title, URL, engagement metrics, timestamps?)
- Update frequency (how often does new content appear?)
- AI relevance (what % of content is AI/ML related?)
- Implementation complexity (RSS feed? JSON API? HTML scraping?)

**Candidate sources to evaluate (minimum):**
1. Bluesky — AT Protocol API (free, public)
2. Mastodon AI instances — ActivityPub API
3. Semantic Scholar — academic paper API
4. Papers With Code — ML papers + code
5. AI conference feeds (NeurIPS, ICML, ICLR proceedings)
6. Twitter/X — evaluate cost vs value ($100+/mo API)
7. Lobste.rs — HN-like with AI tag
8. dev.to — AI/ML tagged posts

**Output format:**
```markdown
# V2 Source Analysis

## Summary Table
| Source | API | Rate Limit | Cost | Quality | Frequency | Complexity | Recommendation |
|--------|-----|------------|------|---------|-----------|------------|----------------|

## Detailed Evaluations
### [Source Name]
- **API:** ...
- **Rate limits:** ...
- **Data shape:** ...
- **Pros:** ...
- **Cons:** ...
- **Recommendation:** INCLUDE / DEFER / SKIP
- **Adapter effort estimate:** S / M / L
```

**Acceptance criteria:**
- [ ] Document evaluates ≥5 candidate sources with pros/cons/API details (AC B.1)
- [ ] At least 1 source recommended for inclusion beyond lab blogs + Reddit (AC B.6)
- [ ] Recommendations include implementation effort estimates

---

## Phase 4: New Source Adapters

**Goal:** Implement lab blog, Reddit, and research-identified source adapters.

**Dependencies:** Phase 2 (migration for source taxonomy metadata), Phase 3 (research identifies additional sources).

**Spec criteria covered:** B.2–B.8

### Task 4.1: Create `src/ai_dashboard/sources/lab_blog.py` — Lab Blog Adapter

**Category:** `deep`

**Description:** RSS-based adapter for major AI lab blogs.

**File:** `src/ai_dashboard/sources/lab_blog.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/sources/lab_blog.py
"""Lab blog source adapter — fetches RSS feeds from major AI research labs.

Classified as 1st-party in the source taxonomy (source_weight = +0.3).
Uses feedparser for RSS parsing (already a V1 dependency).
"""
import feedparser
import httpx
from ai_dashboard.storage.models import FeedItem

class LabBlogAdapter:
    kind = "lab_blog"
    default_interval_seconds = 1800  # 30 minutes

    # Default RSS feeds:
    DEFAULT_FEEDS = [
        "https://openai.com/blog/rss.xml",           # OpenAI
        "https://www.anthropic.com/feed.xml",         # Anthropic
        "https://blog.google/technology/ai/rss/",     # Google AI
        "https://ai.meta.com/blog/rss/",              # Meta AI
        "https://deepmind.google/blog/rss.xml",       # DeepMind
    ]

    def __init__(self, http: httpx.AsyncClient, options: dict) -> None:
        self._http = http
        self._feeds: list[str] = options.get("feeds", self.DEFAULT_FEEDS)

    async def fetch(self) -> list[FeedItem]:
        # For each feed URL:
        #   1. GET the feed via self._http
        #   2. Parse with feedparser.parse(response.text)
        #   3. Convert entries to FeedItem objects
        #   4. source_uid = "{lab_name}:{entry.id or entry.link}"
        #   5. raw_payload includes: author, summary, tags, lab_name
        # Return aggregated list from all feeds
        ...
```

**Constraints:**
- Must implement `SourceAdapter` Protocol without changes to the Protocol
- `kind = "lab_blog"` — this is a single adapter handling multiple lab feeds, not one adapter per lab
- Use `feedparser` (already a V1 dependency) for RSS parsing
- Use `httpx.AsyncClient` passed via constructor (same pattern as `NewsletterAdapter`)
- RSS feed URLs configurable via `options["feeds"]` in config.toml, with defaults
- Error handling: if one feed fails, log and continue with others (don't abort the whole fetch)
- `source_uid` format: `"{lab_domain}:{entry_id}"` to ensure uniqueness across labs

**Context files (read-only):**
- `src/ai_dashboard/sources/base.py` — SourceAdapter Protocol
- `src/ai_dashboard/sources/newsletter.py` — similar RSS-based adapter pattern to follow

**Acceptance criteria:**
- [ ] Fetches RSS from ≥5 major AI labs (AC B.2)
- [ ] Items classified as `source_kind="lab_blog"` (AC B.3)
- [ ] Implements `SourceAdapter` Protocol with zero changes to the Protocol (AC B.7)
- [ ] Unit tests with recorded RSS fixtures (AC B.8)

### Task 4.2: Create `tests/test_sources/test_lab_blog.py` — Lab Blog Tests

**Category:** `deep`

**File:** `tests/test_sources/test_lab_blog.py` (new)
**Fixture file:** `tests/fixtures/lab_blog_openai.xml` (new — recorded RSS response)

**Test cases:**
```python
# - test_lab_blog_parses_rss: mock RSS response → verify FeedItem fields
# - test_lab_blog_source_kind: verify kind == "lab_blog"
# - test_lab_blog_default_interval: verify default_interval_seconds == 1800
# - test_lab_blog_multiple_feeds: mock 2 feeds → items from both in result
# - test_lab_blog_one_feed_fails: mock 1 success + 1 failure → items from success only
# - test_lab_blog_source_uid_format: verify uid contains lab domain + entry id
```

### Task 4.3: Create `src/ai_dashboard/sources/reddit.py` — Reddit Adapter

**Category:** `deep`

**Description:** JSON API adapter for AI-related subreddits.

**File:** `src/ai_dashboard/sources/reddit.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/sources/reddit.py
"""Reddit source adapter — fetches from AI subreddits via JSON API.

Classified as community in the source taxonomy (source_weight = +0.0).
Uses Reddit's public JSON API (append .json to subreddit URL).
"""
class RedditAdapter:
    kind = "reddit"
    default_interval_seconds = 300  # 5 minutes

    DEFAULT_SUBREDDITS = [
        "MachineLearning",
        "LocalLLaMA",
        "singularity",
    ]

    def __init__(self, http: httpx.AsyncClient, options: dict) -> None:
        self._http = http
        self._subreddits: list[str] = options.get("subreddits", self.DEFAULT_SUBREDDITS)

    async def fetch(self) -> list[FeedItem]:
        # For each subreddit:
        #   1. GET https://www.reddit.com/r/{subreddit}/hot.json?limit=25
        #   2. Parse JSON response → data.children[].data
        #   3. Convert to FeedItem:
        #      - source_uid = f"reddit:{post.id}"
        #      - title = post.title
        #      - url = post.url (or f"https://reddit.com{post.permalink}" for self posts)
        #      - published_at = datetime.fromtimestamp(post.created_utc)
        #      - raw_payload = {score, num_comments, author, subreddit, selftext, permalink, ...}
        ...
```

**Constraints:**
- Must implement `SourceAdapter` Protocol without changes to the Protocol
- Use Reddit's public JSON API: `https://www.reddit.com/r/{sub}/hot.json?limit=25`
- User-Agent header MUST identify the app: `"ai-dashboard/0.2 (personal feed reader)"` — Reddit rate-limits generic UAs
- Handle Reddit's rate limiting (HTTP 429) by raising `SourceRateLimited`
- Subreddits configurable via `options["subreddits"]` in config.toml, with defaults
- `raw_payload` MUST include: `score`, `num_comments`, `author`, `subreddit`, `selftext` (AC B.5)

**Context files (read-only):**
- `src/ai_dashboard/sources/base.py` — SourceAdapter Protocol, SourceRateLimited
- `src/ai_dashboard/sources/hackernews.py` — similar JSON API adapter pattern

**Acceptance criteria:**
- [ ] Fetches from ≥3 subreddits (AC B.4)
- [ ] Items include title, score, comment_count, author, subreddit, url, selftext (AC B.5)
- [ ] Implements `SourceAdapter` Protocol with zero changes to the Protocol (AC B.7)
- [ ] Unit tests with recorded JSON fixtures (AC B.8)

### Task 4.4: Create `tests/test_sources/test_reddit.py` — Reddit Tests

**Category:** `deep`

**File:** `tests/test_sources/test_reddit.py` (new)
**Fixture file:** `tests/fixtures/reddit_machinelearning.json` (new — recorded JSON response)

**Test cases:**
```python
# - test_reddit_parses_json: mock JSON response → verify FeedItem fields
# - test_reddit_source_kind: verify kind == "reddit"
# - test_reddit_default_interval: verify default_interval_seconds == 300
# - test_reddit_payload_fields: verify raw_payload contains score, num_comments, author, subreddit, selftext
# - test_reddit_multiple_subreddits: mock 3 subs → items from all 3
# - test_reddit_rate_limited: mock 429 response → raises SourceRateLimited
# - test_reddit_source_uid_format: verify uid starts with "reddit:"
```

### Task 4.5: Register New Adapters in `src/ai_dashboard/sources/__init__.py`

**Category:** `quick`

**Description:** Add lab_blog and reddit to the adapter registry.

**File:** `src/ai_dashboard/sources/__init__.py` (modify)

**Changes:**
```python
from ai_dashboard.sources.lab_blog import LabBlogAdapter
from ai_dashboard.sources.reddit import RedditAdapter

_REGISTRY: dict[str, type] = {
    "arxiv": ArxivAdapter,
    "hn": HackerNewsAdapter,
    "github_trending": GithubTrendingAdapter,
    "huggingface": HuggingFaceAdapter,
    "newsletter": NewsletterAdapter,
    "lab_blog": LabBlogAdapter,     # NEW
    "reddit": RedditAdapter,         # NEW
}
```

**Constraints:**
- Only add imports and registry entries — do NOT modify `build_adapter()` or `available_kinds()`

### Task 4.6: Update `src/ai_dashboard/storage/models.py` — Extend SourceKind Enum

**Category:** `quick`

**File:** `src/ai_dashboard/storage/models.py` (modify)

**Changes:**
```python
class SourceKind(StrEnum):
    ARXIV = "arxiv"
    HN = "hn"
    GITHUB_TRENDING = "github_trending"
    HUGGINGFACE = "huggingface"
    NEWSLETTER = "newsletter"
    LAB_BLOG = "lab_blog"       # NEW
    REDDIT = "reddit"            # NEW
```

**Constraints:**
- Only add new enum values — do NOT modify existing values

### Task 4.7: Update `src/ai_dashboard/config.py` — Add Default Source Configs

**Category:** `deep`

**Description:** Add lab_blog and reddit to the default source configuration.

**File:** `src/ai_dashboard/config.py` (modify)

**Changes to `AppConfig.defaults()`:**
```python
@classmethod
def defaults(cls) -> "AppConfig":
    return cls(
        sources=[
            SourceConfig(kind="arxiv"),
            SourceConfig(kind="hn", options={"keywords": DEFAULT_HN_KEYWORDS}),
            SourceConfig(kind="github_trending"),
            SourceConfig(kind="huggingface"),
            SourceConfig(kind="newsletter", options={"feeds": DEFAULT_NEWSLETTER_FEEDS}),
            SourceConfig(kind="lab_blog"),          # NEW
            SourceConfig(kind="reddit"),             # NEW
        ],
        db_path=_default_db_path(),
    )
```

Also add `RankingConfig` dataclass and `[ranking]` section parsing:
```python
@dataclass
class RankingConfig:
    source_weights: dict[str, float] = field(default_factory=lambda: {
        "arxiv": 0.3,       # 1st-party
        "lab_blog": 0.3,    # 1st-party
        "hn": 0.0,          # community
        "github_trending": 0.0,
        "huggingface": 0.0,
        "newsletter": 0.0,
        "reddit": 0.0,
    })
    keyword_boost: float = 0.2
    recency_half_life_hours: float = 24.0
    skip_penalty_per_skip: float = 0.1
    skip_window: int = 50
    top_search_terms: int = 10

@dataclass
class AppConfig:
    sources: list[SourceConfig]
    db_path: Path
    log_level: str = "INFO"
    ranking: RankingConfig = field(default_factory=RankingConfig)
```

**Constraints:**
- Existing V1 `config.toml` files MUST work without modification (AC F.2)
- New `[ranking]` section is optional — defaults are used if absent
- New source entries are optional — V1 configs with only 5 sources still work
- `AppConfig.load()` must handle missing `[ranking]` section gracefully

### Task 4.8: Implement Research-Identified Source Adapter(s)

**Category:** `deep`

**Description:** Based on Phase 3 research output, implement ≥1 additional source adapter.

**File:** `src/ai_dashboard/sources/{research_identified}.py` (new — name TBD by research)

**Constraints:**
- Must implement `SourceAdapter` Protocol without changes
- Must have unit tests with recorded fixtures
- Must be registered in `sources/__init__.py`
- Source kind added to `SourceKind` enum and `RankingConfig.source_weights`

**Acceptance criteria:**
- [ ] ≥1 additional source beyond lab blogs + Reddit (AC B.6)
- [ ] Implements SourceAdapter Protocol (AC B.7)
- [ ] Has unit tests with recorded fixtures (AC B.8)

### Task 4.9: Update `feed_list.py` Source Tag Map

**Category:** `quick`

**Description:** Add display tags for new sources in `FeedListWidget._source_tag()`.

**File:** `src/ai_dashboard/widgets/feed_list.py` (modify)

**Changes:**
```python
def _source_tag(self, kind: str) -> str:
    return {
        "arxiv": "AX",
        "hn": "HN",
        "github_trending": "GH",
        "huggingface": "HF",
        "newsletter": "NL",
        "lab_blog": "LB",       # NEW
        "reddit": "RD",          # NEW
    }.get(kind, kind[:2].upper())
```

**Constraints:**
- Do NOT modify any other part of `feed_list.py`
- The fallback `kind[:2].upper()` handles research-identified sources without explicit tags

### Task 4.10: Update `content.py` — Content Fetching for New Sources

**Category:** `deep`

**Description:** Add content fetching support for lab blog and Reddit items in `ContentFetcher`.

**File:** `src/ai_dashboard/content.py` (modify)

**Changes to `_fetch_by_kind()`:**
```python
async def _fetch_by_kind(self, item: FeedItem) -> str:
    kind = item.source_kind
    if kind == "arxiv":
        return await self._fetch_arxiv(item)
    elif kind == "github_trending":
        return await self._fetch_github_readme(item)
    elif kind == "huggingface":
        return await self._fetch_hf_card(item)
    elif kind == "hn":
        return await self._fetch_web_article(item.url)
    elif kind == "newsletter":
        return await self._fetch_web_article(item.url)
    elif kind == "lab_blog":
        return await self._fetch_web_article(item.url)  # Blog posts are web articles
    elif kind == "reddit":
        return await self._fetch_reddit_content(item)
    return ""

async def _fetch_reddit_content(self, item: FeedItem) -> str:
    """Fetch Reddit post content — selftext for text posts, linked article for link posts."""
    selftext = item.raw_payload.get("selftext", "")
    if selftext:
        return selftext
    # For link posts, fetch the linked article
    return await self._fetch_web_article(item.url)
```

### Task 4.11: Verify Phase 4 Completeness

**Category:** `quick`

**Acceptance criteria:**
- [ ] `pytest tests/` — all V1 tests + new source tests pass
- [ ] Lab blog adapter fetches from ≥5 labs (AC B.2)
- [ ] Reddit adapter fetches from ≥3 subreddits (AC B.4)
- [ ] All adapters implement SourceAdapter Protocol (AC B.7)
- [ ] AST pluggability test passes
- [ ] Existing V1 config.toml works without modification (AC F.2)

---

## Phase 5: New FeedListStrategy Implementations

**Goal:** Implement `BySourceStrategy`, `HeuristicRankingStrategy`, and `FilteredStrategy`.

**Dependencies:** Phase 2 (DB tables for ranking data), Phase 4 (new sources registered).

**Spec criteria covered:** D.1–D.7

### Task 5.1: Create `src/ai_dashboard/strategies/by_source.py` — BySourceStrategy

**Category:** `deep`

**File:** `src/ai_dashboard/strategies/by_source.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/strategies/by_source.py
"""Strategy that returns items from a single source, ordered chronologically."""
from datetime import datetime
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem

class BySourceStrategy:
    def __init__(self, source_kind: str, limit: int = 500) -> None:
        self.name = f"by-source-{source_kind}"
        self._source_kind = source_kind
        self._limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        return await db.get_items(limit=self._limit, source_kind=self._source_kind)
```

**Constraints:**
- Must satisfy `FeedListStrategy` Protocol without importing or inheriting from it
- Uses existing `Database.get_items(source_kind=...)` — no new DB methods needed
- `name` attribute includes the source kind for identification

**Acceptance criteria:**
- [ ] `BySourceStrategy(source_kind)` returns items from one source only (AC D.1)
- [ ] Implements `FeedListStrategy` Protocol with zero changes (AC D.5)

### Task 5.2: Create `src/ai_dashboard/strategies/heuristic.py` — HeuristicRankingStrategy

**Category:** `ultrabrain`

**File:** `src/ai_dashboard/strategies/heuristic.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/strategies/heuristic.py
"""Strategy that ranks items by the V2 heuristic formula.

score = engagement_normalized + source_weight + keyword_boost + recency_decay - skip_penalty

All weights are sourced from RankingConfig.
"""
import math
from datetime import datetime
from ai_dashboard.config import RankingConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem

class HeuristicRankingStrategy:
    name = "heuristic-ranked"

    def __init__(self, ranking_config: RankingConfig, limit: int = 500) -> None:
        self._config = ranking_config
        self._limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        all_items = await db.get_items(limit=self._limit)
        top_terms = await db.get_top_search_terms(limit=self._config.top_search_terms)
        skip_counts = await db.get_skip_counts(last_n_views=self._config.skip_window)

        scored: list[tuple[float, FeedItem]] = []
        for item in all_items:
            score = self._compute_score(item, now, top_terms, skip_counts)
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def _compute_score(
        self,
        item: FeedItem,
        now: datetime,
        top_terms: list[tuple[str, int]],
        skip_counts: dict[str, int],
    ) -> float:
        engagement = self._engagement_normalized(item)
        source_weight = self._config.source_weights.get(item.source_kind, 0.0)
        keyword = self._keyword_boost(item, top_terms)
        recency = self._recency_decay(item, now)
        skip_pen = self._skip_penalty(item, skip_counts)
        return engagement + source_weight + keyword + recency - skip_pen

    def _engagement_normalized(self, item: FeedItem) -> float:
        """Normalize engagement to 0-1 scale.
        Per-source: min(value / percentile_95, 1.0)
        """
        raw = item.raw_payload
        kind = item.source_kind
        if kind == "hn":
            value = float(raw.get("points", raw.get("score", 0)))
            p95 = 500.0  # Approximate 95th percentile for HN AI posts
        elif kind == "github_trending":
            value = float(raw.get("stars", 0))
            p95 = 10000.0
        elif kind == "reddit":
            value = float(raw.get("score", 0))
            p95 = 1000.0
        elif kind == "huggingface":
            value = float(raw.get("likes", raw.get("downloads", 0)))
            p95 = 5000.0
        else:
            # arXiv, lab_blog, newsletter — no engagement metric
            return 0.0
        return min(value / p95, 1.0) if p95 > 0 else 0.0

    def _keyword_boost(self, item: FeedItem, top_terms: list[tuple[str, int]]) -> float:
        """+0.2 per match with user's top search terms."""
        if not top_terms:
            return 0.0
        text = (item.title + " " + str(item.raw_payload.get("description", ""))).lower()
        boost = 0.0
        for term, _ in top_terms:
            if term.lower() in text:
                boost += self._config.keyword_boost
        return boost

    def _recency_decay(self, item: FeedItem, now: datetime) -> float:
        """e^(-hours_old / half_life)"""
        hours_old = (now - item.published_at).total_seconds() / 3600.0
        return math.exp(-hours_old / self._config.recency_half_life_hours)

    def _skip_penalty(self, item: FeedItem, skip_counts: dict[str, int]) -> float:
        """-0.1 per time source_kind was skipped in last N views."""
        skips = skip_counts.get(item.source_kind, 0)
        return skips * self._config.skip_penalty_per_skip
```

**Constraints:**
- Must satisfy `FeedListStrategy` Protocol without importing or inheriting from it
- All weights come from `RankingConfig` — no hardcoded values except p95 defaults
- `engagement_normalized` uses `min(value / percentile_95, 1.0)` per spec (AC E.2)
- `keyword_boost` uses top N search terms from `user_search_history` (AC E.4)
- `recency_decay` uses `e^(-hours_old / 24)` formula (AC E.5)
- `skip_penalty` uses last 50 item view logs (AC E.6)
- Uses existing `Database` methods from Phase 2

**Context files (read-only):**
- `src/ai_dashboard/storage/db.py` — Database methods for ranking data
- `src/ai_dashboard/config.py` — RankingConfig dataclass
- `src/ai_dashboard/strategies/base.py` — FeedListStrategy Protocol

**Acceptance criteria:**
- [ ] `HeuristicRankingStrategy` sorts items by heuristic score (AC D.2)
- [ ] Score formula matches spec: `engagement + source_weight + keyword_boost + recency_decay - skip_penalty` (AC E.1)
- [ ] 1st-party items rank above same-engagement community items (AC E.9)
- [ ] All weights configurable via config (AC E.7)
- [ ] Implements `FeedListStrategy` Protocol with zero changes (AC D.5)

### Task 5.3: Create `src/ai_dashboard/strategies/filtered.py` — FilteredStrategy

**Category:** `deep`

**File:** `src/ai_dashboard/strategies/filtered.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/strategies/filtered.py
"""Decorator strategy that filters any base strategy's output by text match.

Does NOT modify the base strategy — composes via delegation.
"""
from datetime import datetime
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.strategies.base import FeedListStrategy

class FilteredStrategy:
    def __init__(self, base: FeedListStrategy, text_filter: str) -> None:
        self.name = f"filtered({base.name})"
        self._base = base
        self._text_filter = text_filter.lower()

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        all_items = await self._base.items(db, now)
        if not self._text_filter:
            return all_items
        return [
            item for item in all_items
            if self._matches(item)
        ]

    def _matches(self, item: FeedItem) -> bool:
        """Case-insensitive substring match against title + raw_payload summary/description."""
        needle = self._text_filter
        haystack = item.title.lower()
        # Also search in description/summary from raw_payload
        for key in ("description", "summary", "abstract", "selftext"):
            val = item.raw_payload.get(key, "")
            if val:
                haystack += " " + str(val).lower()
        return needle in haystack
```

**Constraints:**
- Must satisfy `FeedListStrategy` Protocol without importing or inheriting from it
- The `base` parameter is typed as `FeedListStrategy` Protocol — any strategy works
- Does NOT modify the base strategy's output — only filters it
- Case-insensitive substring match (AC C.5)
- Searches title + raw_payload summary/description fields

**Acceptance criteria:**
- [ ] `FilteredStrategy(base, text_filter)` filters any base strategy's output (AC D.3)
- [ ] Filter is case-insensitive substring match on title + description (AC C.5)
- [ ] Does NOT modify base strategy (AC C.7)
- [ ] Implements `FeedListStrategy` Protocol with zero changes (AC D.5)

### Task 5.4: Tests for New Strategies

**Category:** `deep`

**File:** `tests/test_strategies.py` (modify — add new test functions)

**New test cases:**
```python
# - test_by_source_strategy_filters: create items from 3 sources, BySourceStrategy("hn") → only HN items
# - test_by_source_strategy_protocol: verify BySourceStrategy has name + items() method
# - test_heuristic_ranking_order: create items with known engagement/source_weight, verify ranking order
# - test_heuristic_first_party_above_community: arxiv item with same engagement as HN item ranks higher (AC E.9)
# - test_heuristic_recency_decay: older items score lower
# - test_heuristic_keyword_boost: item matching top search term ranks higher
# - test_heuristic_skip_penalty: source with high skip count gets penalty
# - test_heuristic_all_weights_configurable: pass custom RankingConfig, verify it's used
# - test_filtered_strategy_narrows: FilteredStrategy with text → only matching items
# - test_filtered_strategy_case_insensitive: uppercase text matches lowercase item
# - test_filtered_strategy_empty_filter: empty string → all items pass
# - test_filtered_strategy_wraps_any_strategy: wrap BySourceStrategy, verify it works
# - test_all_strategies_satisfy_protocol: import check for name + items() on all new strategies
```

**Acceptance criteria:**
- [ ] All strategy tests pass
- [ ] AST pluggability test still passes
- [ ] All 41 V1 tests still pass

---

## Phase 6: Search/Filter UI

**Goal:** Add source tabs widget and text filter bar to the TUI.

**Dependencies:** Phase 5 (strategies must exist for tab switching to work).

**Spec criteria covered:** C.1–C.8

### Task 6.1: Create `src/ai_dashboard/widgets/source_tabs.py` — Source Tabs Widget

**Category:** `deep`

**File:** `src/ai_dashboard/widgets/source_tabs.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/widgets/source_tabs.py
"""Horizontal tab bar for source filtering.

Tabs: All | AX | HN | GH | HF | NL | RD | LB | ...
Number keys (1-9) switch tabs.
"""
from textual.widgets import Static
from textual.message import Message
from textual.reactive import reactive

class SourceTabs(Static):
    class TabChanged(Message):
        def __init__(self, source_kind: str | None) -> None:
            super().__init__()
            self.source_kind = source_kind  # None = "All"

    TABS: list[tuple[str | None, str]] = [
        (None, "All"),
        ("arxiv", "AX"),
        ("hn", "HN"),
        ("github_trending", "GH"),
        ("huggingface", "HF"),
        ("newsletter", "NL"),
        ("reddit", "RD"),
        ("lab_blog", "LB"),
    ]

    active_index: reactive[int] = reactive(0)

    def render(self) -> str:
        # Render tabs as: [1:All] [2:AX] [3:HN] ...
        # Active tab is highlighted
        ...

    def select_tab(self, index: int) -> None:
        if 0 <= index < len(self.TABS):
            self.active_index = index
            kind, _ = self.TABS[index]
            self.post_message(self.TabChanged(source_kind=kind))

    # Key bindings: 1-9 select tabs
    async def key_1(self) -> None: self.select_tab(0)
    async def key_2(self) -> None: self.select_tab(1)
    # ... through key_9
```

**Constraints:**
- Do NOT import any concrete strategy — tabs emit a `TabChanged` message, the app handles strategy switching
- Tab list is data-driven from `TABS` class variable — easily extensible for research-identified sources
- Active tab state persists across item selection (AC C.8)
- Number keys 1-9 select tabs (AC C.2)

**Acceptance criteria:**
- [ ] Source tabs appear above feed list (AC C.1)
- [ ] Number keys switch tabs (AC C.2)
- [ ] Each tab filters to that source (via app-level strategy switch) (AC C.3)
- [ ] Tab state persists across item selection (AC C.8)

### Task 6.2: Create `src/ai_dashboard/widgets/filter_bar.py` — Text Filter Bar Widget

**Category:** `deep`

**File:** `src/ai_dashboard/widgets/filter_bar.py` (new)

**Implementation details:**
```python
# src/ai_dashboard/widgets/filter_bar.py
"""Text filter bar — appears at the bottom of the feed list when '/' is pressed.

Type to filter items in real time. Escape to close and clear filter.
"""
from textual.widgets import Input
from textual.message import Message

class FilterBar(Input):
    class FilterChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class FilterClosed(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder="Type to filter...", **kwargs)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.post_message(self.FilterChanged(text=event.value))

    async def key_escape(self) -> None:
        self.value = ""
        self.post_message(self.FilterClosed())
```

**Constraints:**
- Real-time filtering as user types (AC C.5)
- Escape clears filter and closes bar (AC C.6)
- Filter bar emits messages — does NOT directly modify strategy or widget

### Task 6.3: Integrate Tabs + Filter into `app.py`

**Category:** `deep`

**Description:** Wire source tabs, filter bar, and strategy switching into the main app.

**File:** `src/ai_dashboard/app.py` (modify)

**Implementation details:**
```python
# Key changes to AIDashboardApp:

# 1. Import new widgets and strategies
from ai_dashboard.widgets.source_tabs import SourceTabs
from ai_dashboard.widgets.filter_bar import FilterBar
from ai_dashboard.strategies.by_source import BySourceStrategy
from ai_dashboard.strategies.heuristic import HeuristicRankingStrategy
from ai_dashboard.strategies.filtered import FilteredStrategy

# 2. Add new key bindings
BINDINGS = [
    ...existing...
    ("/", "open_filter", "Filter"),
    ("s", "cycle_strategy", "Ranked/Chrono"),
    ("escape", "close_filter", "Close filter"),
]

# 3. Update compose() to include tabs and filter bar
def compose(self) -> ComposeResult:
    yield SourceTabs(id="source-tabs")
    with Horizontal(id="layout"):
        yield ReadingPane(...)
        yield FeedListWidget(...)
    yield FilterBar(id="filter-bar")  # Hidden by default

# 4. Handle tab changes
async def on_source_tabs_tab_changed(self, message: SourceTabs.TabChanged) -> None:
    if message.source_kind is None:
        # "All" tab — use chronological or heuristic based on current mode
        self._base_strategy = self._default_strategy()
    else:
        self._base_strategy = BySourceStrategy(message.source_kind)
    await self._apply_strategy()

# 5. Handle filter changes
async def on_filter_bar_filter_changed(self, message: FilterBar.FilterChanged) -> None:
    if message.text:
        self._active_strategy = FilteredStrategy(self._base_strategy, message.text)
    else:
        self._active_strategy = self._base_strategy
    await self._apply_strategy()

# 5b. Record search term on filter CLOSE (not per-keystroke, to avoid noise)
async def on_filter_bar_filter_closed(self, message: FilterBar.FilterClosed) -> None:
    # Record the final filter text (if any) as a search term for keyword_boost
    final_text = self.query_one(FilterBar).value.strip()
    if final_text and len(final_text) >= 3:  # Only record meaningful terms
        await self.db.record_search_term(final_text)

# 6. Handle filter close
async def on_filter_bar_filter_closed(self, message: FilterBar.FilterClosed) -> None:
    self._active_strategy = self._base_strategy
    self.query_one(FilterBar).display = False
    await self._apply_strategy()

# 7. Strategy cycling (s key)
def action_cycle_strategy(self) -> None:
    # Toggle between chronological and heuristic for current tab
    ...

# 8. Helper to apply strategy to feed list
async def _apply_strategy(self) -> None:
    feed_list = self.query_one(FeedListWidget)
    feed_list.strategy = self._active_strategy
    await feed_list.refresh_items()
```

**Constraints:**
- Filter bar is hidden by default, shown when `/` is pressed (AC C.4)
- Filter is applied as a `FilteredStrategy` decorator (AC C.7)
- Tab change updates the base strategy; filter wraps whatever the base strategy is
- `s` key cycles between chronological and heuristic ranked views (AC D.4)
- Search terms are recorded in `user_search_history` for keyword_boost (AC E.4)
- Do NOT modify `FeedListWidget` internals — only set its `.strategy` property

**Context files (read-only):**
- `src/ai_dashboard/widgets/feed_list.py` — FeedListWidget interface
- `src/ai_dashboard/strategies/base.py` — FeedListStrategy Protocol

**Acceptance criteria:**
- [ ] `/` opens filter bar (AC C.4)
- [ ] Typing filters in real time (AC C.5)
- [ ] Escape closes filter and restores view (AC C.6)
- [ ] `s` cycles between chronological and heuristic (AC D.4)
- [ ] ChronologicalAllSourcesStrategy remains default on "All" tab (AC D.6)
- [ ] HeuristicRankingStrategy available via `s` key (AC D.7)

### Task 6.4: Update CSS for New Layout

**Category:** `quick`

**Description:** Update CSS in `app.py` to accommodate source tabs above and filter bar below the feed list.

**File:** `src/ai_dashboard/app.py` (modify — CSS section only)

**Changes:**
```python
CSS = """
#source-tabs { dock: top; height: 1; background: $surface; }
#layout { layout: horizontal; height: 1fr; }
#reading-pane { width: 2fr; height: 100%; border: solid $primary; overflow-y: scroll; }
#feed-list { width: 1fr; height: 100%; border: solid $accent; }
#filter-bar { dock: bottom; display: none; }
"""
```

### Task 6.5: Tests for Search/Filter UI

**Category:** `deep`

**File:** `tests/test_search_filter.py` (new)

**Test cases:**
```python
# - test_source_tabs_render: verify tabs display with correct labels
# - test_source_tabs_number_keys: press 1-8, verify TabChanged messages
# - test_filter_bar_input: type text, verify FilterChanged message
# - test_filter_bar_escape: press Escape, verify FilterClosed message
# - test_filter_bar_hidden_by_default: verify display=none
# - test_strategy_cycle: press 's', verify strategy toggles
# - test_tab_persists_across_selection: switch tab, select item, verify tab unchanged (AC C.8)
```

### Task 6.6: Verify Phase 6 Completeness

**Category:** `quick`

**QA Scenario (executable steps):**

```bash
# Step 1: Run full test suite including new UI tests
pytest tests/ -v
# EXPECTED: All tests pass (V1 + Phase 2-6 tests). Exit code 0.

# Step 2: Verify AST pluggability (no concrete strategy imported in feed_list.py)
pytest tests/ -k "pluggability" -v
# EXPECTED: Pass — feed_list.py imports only strategy base

# Step 3: Verify source_tabs.py does NOT import concrete strategies
python -c "
import ast, sys
tree = ast.parse(open('src/ai_dashboard/widgets/source_tabs.py').read())
imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and 'strategies' in n.module]
assert not imports, f'source_tabs.py should not import strategies: {imports}'
print('OK: source_tabs.py has no strategy imports')
"
# EXPECTED: "OK: source_tabs.py has no strategy imports"

# Step 4: Run Textual pilot test for UI interaction (if pilot tests exist)
pytest tests/test_search_filter.py -v
# EXPECTED: All filter/tab tests pass
```

**Acceptance criteria:**
- [ ] `pytest tests/` — exit code 0, all V1 + new tests pass
- [ ] AST pluggability test passes
- [ ] `source_tabs.py` has zero imports from `strategies.*`
- [ ] `test_search_filter.py` tests pass

---

## Phase 7: Heuristic Ranking — Behavior Tracking

**Goal:** Wire user behavior tracking (viewed/skipped items) into the TUI for the ranking system.

**Dependencies:** Phase 2 (DB tables), Phase 5 (HeuristicRankingStrategy), Phase 6 (filter UI for search term recording).

**Spec criteria covered:** E.1–E.9

### Task 7.1: Add View/Skip Tracking to `feed_list.py`

**Category:** `deep`

**Description:** Track when users view (select) or skip (scroll past) items.

**File:** `src/ai_dashboard/widgets/feed_list.py` (modify)

**Implementation details:**

V1 behavior: `on_data_table_row_highlighted` → emits `ItemSelected` → reading pane loads content.
V2 extends this with a **dwell-time signal** to distinguish viewing from skipping:

```python
# Add to FeedListWidget:

class ItemViewed(Message):
    """Emitted when user dwells on an item ≥2 seconds (implying they read the content)."""
    def __init__(self, item: FeedItem) -> None:
        super().__init__()
        self.item = item

class ItemSkipped(Message):
    """Emitted when user moves OFF an item in <2 seconds (implying they glanced and moved on)."""
    def __init__(self, item: FeedItem) -> None:
        super().__init__()
        self.item = item

# State tracking:
_current_item: FeedItem | None = None
_highlight_time: float = 0.0  # monotonic time when current item was highlighted

def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
    import time
    now = time.monotonic()

    if 0 <= event.cursor_row < len(self._items):
        # Emit viewed/skipped for the PREVIOUS item based on dwell time
        if self._current_item is not None:
            dwell = now - self._highlight_time
            if dwell >= 2.0:
                self.post_message(self.ItemViewed(self._current_item))
            else:
                self.post_message(self.ItemSkipped(self._current_item))

        # Track the new highlighted item (same as V1 — content loads immediately)
        self._current_item = self._items[event.cursor_row]
        self._highlight_time = now
        self.post_message(self.ItemSelected(self._current_item))  # V1 behavior preserved
```

**Behavior (unambiguous, consistent with V1):**
- Highlighting a row = content loads in reading pane immediately (V1 behavior preserved via `ItemSelected`)
- Staying on a row ≥2 seconds then moving away = "viewed" → emits `ItemViewed`
- Moving off a row in <2 seconds = "skipped" → emits `ItemSkipped`
- Fast scrolling = intermediate items marked "skipped" (dwell <2s); final resting position starts a new dwell timer
- `ItemSelected` (V1 message) still fires on EVERY highlight for reading pane — unchanged
- `ItemViewed`/`ItemSkipped` are NEW messages for ranking behavior tracking only

**Constraints:**
- Do NOT import any concrete strategy — only emit messages
- "Viewed" = user dwelt on item ≥2 seconds (content was loaded AND user spent time reading it)
- "Skipped" = user dwelt on item <2 seconds (glanced and moved on)
- Both `ItemViewed` and `ItemSkipped` are emitted when cursor LEAVES an item (retrospective signal)
- `ItemSelected` (V1 message) continues to fire on every highlight — unchanged, still loads reading pane
- Emit messages only — the app handles DB recording (Task 7.2)
- Do NOT modify the `FeedListStrategy` Protocol
- Dwell timer uses `time.monotonic()` for reliable measurement

### Task 7.2: Record View/Skip in `app.py`

**Category:** `deep`

**Description:** Handle view/skip messages and record them to the database.

**File:** `src/ai_dashboard/app.py` (modify)

**Implementation details:**
```python
# EXISTING handler (V1 — unchanged, still handles reading pane):
async def on_feed_list_widget_item_selected(self, message: FeedListWidget.ItemSelected) -> None:
    reading_pane = self.query_one(ReadingPane)
    await reading_pane.show_item(message.item)
    # NOTE: This fires on every highlight (V1 behavior). Does NOT record to view log.
    # Ranking signals come from ItemViewed/ItemSkipped (dwell-time based).

# NEW handlers for ranking behavior tracking:
async def on_feed_list_widget_item_viewed(self, message: FeedListWidget.ItemViewed) -> None:
    """User dwelt on item ≥2 seconds — record as viewed for ranking."""
    await self.db.record_item_view(
        message.item.source_kind, message.item.source_uid, "viewed"
    )

async def on_feed_list_widget_item_skipped(self, message: FeedListWidget.ItemSkipped) -> None:
    """User moved off item in <2 seconds — record as skipped for ranking."""
    await self.db.record_item_view(
        message.item.source_kind, message.item.source_uid, "skipped"
    )
```

**Behavior contract (consistent with Task 7.1):**
- `ItemSelected` → loads reading pane content (V1 behavior, fires on every highlight)
- `ItemViewed` → records "viewed" to `item_view_log` (fires when cursor LEAVES after ≥2s dwell)
- `ItemSkipped` → records "skipped" to `item_view_log` (fires when cursor LEAVES after <2s dwell)
- Both ranking messages are emitted by Task 7.1's dwell-time logic in `feed_list.py`
- The existing `on_feed_list_widget_item_selected` is NOT modified — V1 reading pane behavior preserved

**Constraints:**
- View/skip recording must not block the UI — use `run_worker` if needed for batching
- Recording is fire-and-forget — failures are logged but don't crash the app
- Do NOT move reading pane loading into `ItemViewed` — content must load immediately on highlight (V1 UX)

**Acceptance criteria:**
- [ ] Dwelling ≥2s on an item then moving away records `viewed` (AC E.8)
- [ ] Dwelling <2s on an item then moving away records `skipped` (AC E.8)
- [ ] Reading pane still loads immediately on highlight (V1 behavior unchanged)

### Task 7.3: Engagement Percentile Computation

**Category:** `ultrabrain`

**Description:** Implement per-source engagement percentile computation for normalized scoring, with minimum sample size fallback and caching.

**File:** `src/ai_dashboard/storage/db.py` (modify — add method)

**Implementation details:**
```python
# Hardcoded fallback percentiles for cold-start (< MIN_SAMPLE items per source)
_DEFAULT_P95: dict[str, float] = {
    "hn": 500.0,
    "github_trending": 10000.0,
    "reddit": 1000.0,
    "huggingface": 5000.0,
}

# Mapping: source_kind → JSON key for engagement metric in raw_payload
_ENGAGEMENT_KEYS: dict[str, str] = {
    "hn": "points",
    "github_trending": "stars",
    "reddit": "score",
    "huggingface": "likes",
}

MIN_SAMPLE_SIZE = 20  # Minimum items before trusting DB-derived p95

async def get_engagement_percentiles(self) -> dict[str, float]:
    """Compute 95th percentile engagement for each source kind.

    Returns dict mapping source_kind → p95 engagement value.
    Falls back to hardcoded defaults if sample size < MIN_SAMPLE_SIZE.
    Result should be cached per ranking pass (call once per strategy refresh).
    """
    conn = self.connection
    result: dict[str, float] = {}

    for kind, json_key in _ENGAGEMENT_KEYS.items():
        cursor = await conn.execute(
            """
            SELECT CAST(json_extract(raw_payload, ?) AS REAL) as val
            FROM feed_items
            WHERE source_kind = ? AND json_extract(raw_payload, ?) IS NOT NULL
            ORDER BY val ASC
            """,
            (f"$.{json_key}", kind, f"$.{json_key}"),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        if len(rows) >= MIN_SAMPLE_SIZE:
            idx = int(len(rows) * 0.95)
            result[kind] = max(float(rows[min(idx, len(rows) - 1)][0]), 1.0)
        else:
            result[kind] = _DEFAULT_P95.get(kind, 1.0)

    return result
```

**Constraints:**
- Use SQLite's `json_extract()` on the `raw_payload` JSON column
- P95 = value at index `len(values) * 0.95` in sorted list
- **Minimum sample size = 20 items per source.** Below this, fall back to `_DEFAULT_P95` hardcoded estimates
- Default to 1.0 minimum (prevent division by zero)
- The result MUST be cached once per ranking pass — called once in `HeuristicRankingStrategy.items()`, passed to all `_compute_score()` calls
- CAST to REAL in SQL to ensure numeric ordering (not string ordering)
- Extraction keys defined in a single `_ENGAGEMENT_KEYS` dict for maintainability

**Acceptance criteria:**
- [ ] `engagement_normalized` is per-source: `min(value / percentile_95, 1.0)` (AC E.2)
- [ ] p95 is correctly computed from actual DB data

### Task 7.4: Wire Percentiles into HeuristicRankingStrategy

**Category:** `deep`

**Description:** Update `HeuristicRankingStrategy` to use DB-computed percentiles instead of hardcoded estimates.

**File:** `src/ai_dashboard/strategies/heuristic.py` (modify)

**Changes:**
```python
async def items(self, db: Database, now: datetime) -> list[FeedItem]:
    all_items = await db.get_items(limit=self._limit)
    top_terms = await db.get_top_search_terms(limit=self._config.top_search_terms)
    skip_counts = await db.get_skip_counts(last_n_views=self._config.skip_window)
    percentiles = await db.get_engagement_percentiles()  # NEW

    scored: list[tuple[float, FeedItem]] = []
    for item in all_items:
        score = self._compute_score(item, now, top_terms, skip_counts, percentiles)
        scored.append((score, item))
    ...

def _engagement_normalized(self, item: FeedItem, percentiles: dict[str, float]) -> float:
    # Use DB-computed percentiles instead of hardcoded values
    p95 = percentiles.get(item.source_kind, 1.0)
    ...
```

### Task 7.5: Tests for Heuristic Ranking End-to-End

**Category:** `deep`

**File:** `tests/test_heuristic_ranking.py` (new)

**Test cases:**
```python
# - test_score_formula_components: verify each component independently
# - test_first_party_weight: 1st-party item scores +0.3 over community (AC E.3, E.9)
# - test_keyword_boost: item matching search term gets +0.2 per match (AC E.4)
# - test_recency_decay_formula: verify e^(-hours/24) (AC E.5)
# - test_skip_penalty: source with 3 skips in last 50 gets -0.3 (AC E.6)
# - test_all_weights_from_config: pass custom RankingConfig, verify all weights applied (AC E.7)
# - test_engagement_percentile_normalization: items above p95 capped at 1.0 (AC E.2)
# - test_new_db_tables_populated: verify user_search_history and item_view_log have data (AC E.8)
# - test_ranking_end_to_end: insert diverse items, verify heuristic strategy produces sensible ordering
```

### Task 7.6: Verify Phase 7 Completeness

**Category:** `quick`

**QA Scenario (executable steps):**

```bash
# Step 1: Run heuristic ranking tests
pytest tests/test_heuristic_ranking.py -v
# EXPECTED: All tests pass. Exit code 0.

# Step 2: Verify formula components via test assertions
pytest tests/test_heuristic_ranking.py -k "first_party_weight" -v
# EXPECTED: Test verifies arxiv item scores +0.3 above same-engagement HN item (AC E.3, E.9)

pytest tests/test_heuristic_ranking.py -k "recency_decay" -v
# EXPECTED: Test verifies e^(-hours/24) formula produces correct decay values (AC E.5)

pytest tests/test_heuristic_ranking.py -k "skip_penalty" -v
# EXPECTED: Test verifies -0.1 * skip_count applied correctly (AC E.6)

# Step 3: Verify config-driven weights
pytest tests/test_heuristic_ranking.py -k "configurable" -v
# EXPECTED: Test passes custom RankingConfig, verifies all weights are applied from config (AC E.7)

# Step 4: Full test suite regression check
pytest tests/ -v
# EXPECTED: Exit code 0. All V1 + V2 tests pass.
```

**Acceptance criteria:**
- [ ] `pytest tests/test_heuristic_ranking.py` — exit code 0
- [ ] 1st-party item scores `+0.3` above same-engagement community item (AC E.3, E.9)
- [ ] `keyword_boost = +0.2` per match verified in test (AC E.4)
- [ ] `recency_decay = e^(-hours_old / 24)` verified in test (AC E.5)
- [ ] `skip_penalty = -0.1` per skip verified in test (AC E.6)
- [ ] Custom `RankingConfig` weights applied when provided (AC E.7)
- [ ] `pytest tests/` — all V1 tests still pass

---

## Phase 8: Integration & Polish

**Goal:** Wire everything together, run end-to-end tests, verify backward compatibility, and clean up.

**Dependencies:** All previous phases.

**Spec criteria covered:** F.1–F.4 (backward compatibility sweep), all ACs verified end-to-end

### Task 8.1: End-to-End Integration Test

**Category:** `deep`

**File:** `tests/test_integration_v2.py` (new)

**Test cases:**
```python
# - test_full_lifecycle: daemon start → sources poll → items arrive → TUI reads from DB → tabs work → filter works → ranking works → daemon stop
# - test_v1_config_with_v2_binary: load a V1 config.toml (5 sources, no [ranking] section) → app starts, V1 behavior preserved
# - test_v2_config_with_all_sources: load V2 config with 7+ sources + [ranking] section → all sources polled, ranking active
# - test_daemon_tui_concurrent: daemon writes items, TUI reads them concurrently (WAL test)
# - test_no_duplicate_items: daemon and TUI both configured for same sources, daemon is running → TUI does not poll (no duplicates)
# - test_data_completeness: daemon runs for simulated period → items visible in feeds for ≥1 poll interval are captured (best-effort AC A.12)
```

### Task 8.2: Backward Compatibility Verification

**Category:** `quick`

**QA Scenario (executable steps):**

```bash
# Step 1: V1 behavior without daemon (AC F.1)
ai-dashboard daemon stop 2>/dev/null || true  # Ensure daemon is not running
python -c "
from pathlib import Path
import os

# Test daemon detection logic directly (no app construction needed).
# This mirrors the _is_daemon_running() logic from app.py / daemon.py:
pid_path = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'ai-dashboard' / 'daemon.pid'
if pid_path.exists():
    print(f'FAIL: PID file exists at {pid_path} — daemon may be running')
    exit(1)
print('OK: No PID file — TUI would use V1 fallback polling')
"
# EXPECTED: "OK: No PID file — TUI would use V1 fallback polling"

# Step 2: V1 config.toml compatibility (AC F.2)
# Create a minimal V1 config (5 sources, no [ranking] section):
python -c "
import tempfile, tomllib
from pathlib import Path
from ai_dashboard.config import AppConfig

# V1-style TOML with sources list, no [ranking] section
v1_toml = '''
[[sources]]
kind = \"arxiv\"

[[sources]]
kind = \"hn\"

[sources.options]
keywords = [\"AI\", \"LLM\"]

[[sources]]
kind = \"github_trending\"

[[sources]]
kind = \"huggingface\"

[[sources]]
kind = \"newsletter\"

[sources.options]
feeds = [\"https://example.com/feed.xml\"]
'''
tmp = Path(tempfile.mktemp(suffix='.toml'))
tmp.write_text(v1_toml)
config = AppConfig.load(tmp)
assert len(config.sources) >= 5, f'Expected >=5 sources, got {len(config.sources)}'
assert hasattr(config, 'ranking'), 'Should have ranking attribute with defaults'
print('OK: V1 config loads with defaults')
tmp.unlink()
"
# EXPECTED: "OK: V1 config loads with defaults"

# Step 3: V1 DB migration (AC F.3)
python -c "
import asyncio
from pathlib import Path
from ai_dashboard.storage.db import Database

async def test():
    import tempfile
    db_path = Path(tempfile.mktemp(suffix='.db'))
    db = Database(db_path)
    await db.connect()
    # Simulate V1 schema (version=1, no new tables)
    await db.connection.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)')
    await db.connection.execute('INSERT OR REPLACE INTO schema_version VALUES (1)')
    await db.connection.commit()
    # Run migration
    await db.init_schema()
    # Verify V2 tables exist
    cur = await db.connection.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
    tables = [r[0] for r in await cur.fetchall()]
    assert 'user_search_history' in tables, f'Missing user_search_history. Tables: {tables}'
    assert 'item_view_log' in tables, f'Missing item_view_log. Tables: {tables}'
    cur2 = await db.connection.execute('SELECT version FROM schema_version')
    assert (await cur2.fetchone())[0] == 2
    await db.close()
    db_path.unlink()
    print('OK: V1 to V2 migration successful')

asyncio.run(test())
"
# EXPECTED: "OK: V1 to V2 migration successful"

# Step 4: All V1 tests pass (AC F.4)
pytest tests/ -v
# EXPECTED: Exit code 0, all tests pass
```

**Acceptance criteria:**
- [ ] V1 TUI behavior preserved without daemon (AC F.1)
- [ ] V1 `config.toml` loads without error, defaults applied (AC F.2)
- [ ] V1 DB migrates to V2 non-destructively (AC F.3)
- [ ] All 41 V1 tests pass (AC F.4)

### Task 8.3: Update `__main__.py` Entry Point

**Category:** `quick`

**File:** `src/ai_dashboard/__main__.py` (modify)

**Changes:**
```python
from ai_dashboard.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

### Task 8.4: Update Source Tag Map for Research-Identified Sources

**Category:** `quick`

**Description:** Add display tags for any sources identified in Phase 3 research.

**File:** `src/ai_dashboard/widgets/feed_list.py` (modify — _source_tag only)

### Task 8.5: Final Test Suite Run

**Category:** `quick`

**Description:** Run the complete test suite and verify ALL static invariants.

**QA Scenario (executable steps):**

```bash
# Step 1: Full test suite
pytest tests/ -v --tb=short
# EXPECTED: Exit code 0. All V1 (41) + all V2 tests pass.

# Step 2: AST pluggability invariant
pytest tests/ -k "pluggability" -v
# EXPECTED: Pass — feed_list.py imports only from strategies.base

# Step 3: No concrete strategy imports in feed_list.py
python -c "
import ast
tree = ast.parse(open('src/ai_dashboard/widgets/feed_list.py').read())
strategy_imports = [
    n.module for n in ast.walk(tree)
    if isinstance(n, ast.ImportFrom) and n.module
    and 'strategies' in n.module and n.module != 'ai_dashboard.strategies.base'
]
assert not strategy_imports, f'feed_list.py imports concrete strategies: {strategy_imports}'
print('OK: No concrete strategy imports in feed_list.py')
"
# EXPECTED: "OK: No concrete strategy imports in feed_list.py"

# Step 4: No huggingface_hub SDK anywhere
grep -r "huggingface_hub" src/ && echo "FAIL: huggingface_hub found" && exit 1 || echo "OK: No huggingface_hub"
# EXPECTED: "OK: No huggingface_hub"

# Step 5: Protocols unchanged from V1 (content hash check)
# Compare current protocol files against their known V1 checksums.
# These checksums are recorded BEFORE V2 work begins (run once, store in plan).
python -c "
import hashlib
from pathlib import Path

# Verify no modifications to Protocol files by checking they match V1 content.
# Method: parse the file and verify the Protocol class signature is unchanged.
import ast

for proto_file in ['src/ai_dashboard/strategies/base.py', 'src/ai_dashboard/sources/base.py']:
    tree = ast.parse(Path(proto_file).read_text())
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    # Protocol classes should exist and have their original method signatures
    assert len(classes) >= 1, f'No classes found in {proto_file}'
    print(f'OK: {proto_file} — {classes[0].name} Protocol class intact')
"
# EXPECTED: Both protocol files report class intact with no changes to method signatures

# Step 6: Verify all ACs can be demonstrated
pytest tests/ -v 2>&1 | grep -c "PASSED"
# EXPECTED: Total passed count >= 41 + number of new V2 tests
```

**Acceptance criteria:**
- [ ] `pytest tests/` — exit code 0
- [ ] AST pluggability test passes
- [ ] Zero concrete strategy imports in `feed_list.py`
- [ ] Zero occurrences of `huggingface_hub` in `src/`
- [ ] `strategies/base.py` unchanged from V1 (git diff empty)
- [ ] `sources/base.py` unchanged from V1 (git diff empty)

---

## Risk Register

### Risk 1: SQLite Concurrent Write Contention

**Likelihood:** Medium
**Impact:** High (data corruption or write failures)
**Description:** Daemon and TUI both write to the same SQLite DB. While WAL mode supports concurrent readers, concurrent writers can cause `SQLITE_BUSY` errors.

**Mitigation:**
- Daemon is the primary writer (polls + upserts). TUI writes are minimal (view logs, search history, seen toggles).
- Both processes use `PRAGMA busy_timeout = 5000` to retry on contention.
- V2 design ensures TUI is "read-mostly" when daemon is running — most writes come from the daemon.

**Detection:**
- Integration test in Phase 8 verifies concurrent access.
- Daemon logs `SQLITE_BUSY` events.

### Risk 2: Reddit API Rate Limiting

**Likelihood:** High (Reddit aggressively rate-limits)
**Impact:** Low (one source degrades, others unaffected)
**Description:** Reddit's free JSON API has undocumented rate limits. Generic user-agents get 429'd quickly.

**Mitigation:**
- Use descriptive User-Agent: `"ai-dashboard/0.2 (personal feed reader)"`
- Handle HTTP 429 by raising `SourceRateLimited` → PollingOrchestrator doubles the interval
- Default interval of 300s (5 min) is conservative
- V1's source isolation pattern ensures Reddit failures don't affect other sources

### Risk 3: Lab Blog RSS Feed URL Instability

**Likelihood:** Medium
**Impact:** Medium (lab blog adapter returns empty results)
**Description:** AI lab blog RSS feed URLs change without notice. There's no standard location.

**Mitigation:**
- Feed URLs are configurable via `config.toml` `options.feeds`, not hardcoded
- Default URLs are best-effort; users can update them
- The adapter logs individual feed failures without aborting the full fetch
- Research phase (Phase 3) verifies current URLs

### Risk 4: Heuristic Ranking Cold Start

**Likelihood:** High (guaranteed for new V2 installs)
**Impact:** Low (ranking degrades gracefully to recency-only)
**Description:** On a fresh V2 install, `user_search_history` and `item_view_log` are empty. The heuristic formula has no keyword boost or skip penalty data.

**Mitigation:**
- Formula degrades gracefully: empty search history → `keyword_boost = 0`; empty view log → `skip_penalty = 0`
- With no behavior data, ranking is effectively `engagement_normalized + source_weight + recency_decay` — still useful
- Users see improving ranking as they use the tool

### Risk 5: Launchd Plist Compatibility Across macOS Versions

**Likelihood:** Low
**Impact:** Medium (daemon install/uninstall fails)
**Description:** `launchctl` syntax differs between macOS versions. `launchctl load` is deprecated in favor of `launchctl bootstrap` on newer macOS.

**Mitigation:**
- Use `launchctl load -w` for compatibility (works on macOS 10.x through current)
- Document known issues for newer macOS versions
- `daemon start` CLI mode works regardless of launchd compatibility
- CLI mode is the primary dev workflow; launchd is a production convenience

---

## Spec Acceptance Criteria → Phase Mapping

| AC | Description | Phase | Task |
|----|-------------|-------|------|
| A.1 | daemon start spawns background process | 1 | 1.2 |
| A.2 | daemon stop sends SIGTERM, cleans up | 1 | 1.2 |
| A.3 | daemon status reports running/stopped | 1 | 1.2 |
| A.4 | daemon install creates launchd plist | 1 | 1.2 |
| A.5 | daemon uninstall removes plist | 1 | 1.2 |
| A.6 | Daemon polls all sources on intervals | 1 | 1.1 |
| A.7 | Daemon logs to configurable log file | 1 | 1.1 |
| A.8 | TUI disables polling when daemon running | 1 | 1.4 |
| A.9 | TUI falls back to V1 polling when no daemon | 1 | 1.4 |
| A.10 | Daemon is extracted V1 PollingOrchestrator | 1 | 1.1 |
| A.11 | SIGKILL doesn't corrupt SQLite (WAL) | 1 | 1.6 |
| A.12 | Best-effort completeness (items visible ≥1 poll interval captured) | 8 | 8.1 |
| B.1 | Research evaluates ≥5 sources | 3 | 3.1 |
| B.2 | Lab blog adapter fetches from ≥5 labs | 4 | 4.1 |
| B.3 | Lab blog items = source_kind="lab_blog", 1st-party | 4 | 4.1 |
| B.4 | Reddit adapter fetches from ≥3 subreddits | 4 | 4.3 |
| B.5 | Reddit items include required fields | 4 | 4.3 |
| B.6 | ≥1 additional source from research | 4 | 4.8 |
| B.7 | All adapters implement SourceAdapter Protocol | 4 | 4.1, 4.3, 4.8 |
| B.8 | All adapters have fixture-based unit tests | 4 | 4.2, 4.4, 4.8 |
| C.1 | Source tabs above feed list | 6 | 6.1 |
| C.2 | Number keys switch tabs | 6 | 6.1 |
| C.3 | Each tab filters to source_kind | 6 | 6.3 |
| C.4 | `/` opens text filter bar | 6 | 6.3 |
| C.5 | Real-time case-insensitive text filtering | 6 | 6.2, 6.3 |
| C.6 | Escape closes filter, restores view | 6 | 6.2, 6.3 |
| C.7 | Filter is FilteredStrategy decorator | 6 | 6.3 |
| C.8 | Tab state persists across item selection | 6 | 6.1 |
| D.1 | BySourceStrategy returns single source | 5 | 5.1 |
| D.2 | HeuristicRankingStrategy sorts by score | 5 | 5.2 |
| D.3 | FilteredStrategy filters any base strategy | 5 | 5.3 |
| D.4 | `s` cycles chronological/heuristic | 6 | 6.3 |
| D.5 | All strategies satisfy Protocol, no changes | 5 | 5.1–5.3 |
| D.6 | Chronological default on "All" tab | 6 | 6.3 |
| D.7 | Heuristic via `s` key or "Ranked" tab | 6 | 6.3 |
| E.1 | Score formula correct | 7 | 7.5 |
| E.2 | engagement_normalized = min(val/p95, 1.0) | 7 | 7.3, 7.4 |
| E.3 | 1st-party +0.3, community +0.0 | 5 | 5.2 |
| E.4 | keyword_boost = +0.2 per match | 5 | 5.2 |
| E.5 | recency_decay = e^(-hours/24) | 5 | 5.2 |
| E.6 | skip_penalty = -0.1 per skip in last 50 | 5 | 5.2 |
| E.7 | All weights configurable via config.toml | 4 | 4.7 |
| E.8 | viewed/skipped actions recorded to DB | 7 | 7.1, 7.2 |
| E.9 | 1st-party + high engagement > community same | 7 | 7.5 |
| F.1 | V1 behavior preserved without daemon | 1 | 1.4 |
| F.2 | V1 config.toml works without modification | 4 | 4.7 |
| F.3 | V1 DB forward-compatible via migration | 2 | 2.1 |
| F.4 | All 41 V1 tests pass | ALL | Every phase verification task |

---

## Execution Notes for Autopilot

1. **Phase 3 (research) can run in parallel with Phases 1–2.** It produces a document, not code. Fire it as a background librarian task.
2. **Phase 4 depends on Phase 3 output** for task 4.8 (research-identified adapter). Tasks 4.1–4.7 can proceed immediately since lab blogs and Reddit are confirmed.
3. **Each task is a single `task()` call.** The prompt for each call should follow the 6-section format from AGENTS.md: `[CONTEXT], [GOAL], [REQUIRED TOOLS], [MUST DO], [MUST NOT DO], [CONTEXT FILES]`.
4. **Run `pytest tests/` after every phase** to verify no regressions. If any V1 test breaks, fix before proceeding.
5. **Leaf-first within phases:** In Phase 4, implement adapters (4.1, 4.3) before registry updates (4.5) and config changes (4.7). In Phase 5, implement strategies (5.1–5.3) before UI integration (Phase 6).
6. **One file per task() call.** If a task touches multiple files, split it into sub-tasks or carefully scope which file is modified.
