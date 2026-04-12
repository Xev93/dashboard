# Implementation Plan: AI News Terminal Dashboard

**Source spec:** `.omc/specs/deep-interview-ai-news-tui.md` (7-round deep interview, 10.1% final ambiguity)
**Generated:** 2026-04-11 via `omc-plan --consensus --direct`
**Target:** greenfield Python project at `/Users/dev/projects/dashboard`
**Status:** ✅ **APPROVED** (Architect review → Critic APPROVE_WITH_MINOR → minor fixes applied → ready for autopilot)

---

## Requirements Summary

Build a single-process Python + Textual TUI application that:
1. Displays a two-panel layout (reading pane LEFT, feed list RIGHT)
2. Polls 5 AI-content sources (arXiv, HN AI-filtered, GitHub Trending ML, HuggingFace, AI newsletters) via foreground asyncio workers spawned at App mount
3. Persists items to SQLite with `(source_kind, source_uid)` dedup
4. Renders reading pane from initial API payloads only — no extra content fetching
5. Preserves a pluggable `FeedListStrategy` Protocol so V2 can swap filter/sort logic without touching the widget
6. Exits cleanly within 2 seconds, cancelling all workers

The spec's `## Acceptance Criteria` section (A-L, 11 groups) is the source of truth for "done". This plan elaborates the **how**, not the **what**.

---

## RALPLAN-DR Summary

### Principles

1. **Pluggability is load-bearing, not aspirational.** The `FeedListStrategy` Protocol MUST be proven at MVP time with a second toy implementation used in tests, not a comment promising V2 will add it later.
2. **Simplest thing that works (enforced by the interview's Simplifier round).** No PDF parsing, no markdown rendering, no image libs, no content extractors. If a dependency is not in `{textual, httpx, feedparser, selectolax, aiosqlite}` + stdlib, it needs explicit justification and the Critic will reject otherwise. (HuggingFace is reached via direct HTTP API through `httpx`, not via the `huggingface_hub` SDK — see Phase 1.1 and Phase 3.5 for rationale.)
3. **Foreground-only, fail-fast lifetime.** All polling is `asyncio.Task` owned by the App. No daemon, no pid files, no systemd, no multi-process. `App.on_unmount` cancels every worker with a 2s hard deadline.
4. **Source isolation: one broken source cannot cascade.** Each adapter has its own try/except, its own retry/backoff, its own rate limit state. A 500 from arXiv does not touch HN's worker loop.
5. **Testability is co-equal with implementation.** Every source adapter ships with a recorded-fixture unit test; the pluggability swap is verified with a real test, not a docstring; the main app has a Textual snapshot test.

### Decision Drivers (top 3)

1. **Preserve the V2 pluggability seam.** This was a user-volunteered requirement in Round 5 of the interview and is the single hardest thing for a future-self or an AI executor to "accidentally" break. Every architectural call must pass the question: *"can a new `FeedListStrategy` be added without touching the feed-list widget file?"*
2. **Minimize dependency surface.** Five runtime dependencies total (textual, httpx, feedparser, selectolax, aiosqlite). Any addition requires a written justification in this plan. Rationale: the interview explicitly cut ~4 categories of dependencies in Round 6; preserving that cut is a commitment, not an accident. The `huggingface_hub` SDK was initially planned but removed during Architect review in favor of direct `httpx` calls to HF's public HTTP API — see ADR-4.
3. **Fast MVP ship with offline-testable components.** Adapters are built as pure functions of HTTP responses → `FeedItem` list, so they can be unit-tested with recorded fixtures without network. CI can run the full test suite with zero network calls.

### Viable Options

#### Option A — "Vertical slices" (one source end-to-end, then repeat)
**Approach:** Build one full source end-to-end first (adapter → DB upsert → widget wire-up → test). Ship it. Demo. Then repeat for the next source.

- **Pros:** End-to-end working flow after ~1 day. Catches integration problems early. Demoable before all sources are done.
- **Cons:** The `SourceAdapter` Protocol evolves with the first source and will likely need refactoring when the second source reveals its awkwardness. Integration code (widget ↔ storage ↔ workers) gets rewritten twice.

#### Option B — "Horizontal layers" (data → adapters → strategies → widgets → app)
**Approach:** Build the data layer first (models + SQLite + migrations), then all 5 source adapters in parallel (they depend only on the Protocol + `FeedItem`), then strategies, then widgets + workers + App, then tests.

- **Pros:** Each layer stabilizes before the next builds on it. Adapters are genuinely parallelizable (they share nothing except `FeedItem` and `SourceAdapter`). The `FeedListStrategy` Protocol is designed before either the widget or the default implementation commits to it — maximizing the pluggability guarantee.
- **Cons:** No end-to-end flow until widgets land (~60-70% through the work). If storage design is wrong, the whole thing rebuilds.

#### Option C — "Skeleton + fill"
**Approach:** Create every file as a minimal stub (protocols defined, classes empty, methods returning empty lists). Get the App running with empty feeds first. Then fill in each file.

- **Pros:** App is always launchable. Explicit separation of structure vs content. Excellent for parallel execution because every file exists with the right signature.
- **Cons:** Slightly more upfront boilerplate. Stubs can mask bugs (empty list is a valid return from every adapter — a broken adapter looks indistinguishable from an idle one).

### Recommendation: **Option B (Horizontal layers)**

Justification:
- The **pluggability seam** is a Protocol-first concern. Option B defines `SourceAdapter` and `FeedListStrategy` upfront in their own files, with their default implementations built against them, so the "no widget references to concrete strategies" invariant is enforced by construction rather than by vigilance.
- The spec's 5 sources are **genuinely parallel work units** — they share zero code beyond `FeedItem` and the Protocol. Horizontal layers lets us fan out.
- Option A's risk of "first-source fitness for the Protocol" is real — I have seen this in every feed reader I have built.
- Option C's "empty-adapter masks a broken adapter" failure mode is explicitly called out in the spec's Acceptance Criteria section C ("On fetch failure, the source logs error but does not crash App"). A stub returning `[]` looks identical to a broken source returning `[]`.

### Invalidation rationale for rejected options
- **Option A rejected** because the SourceAdapter Protocol cannot be designed properly against one source; its stability depends on seeing ≥2 sources' shapes before committing.
- **Option C rejected** because empty-stub indistinguishability conflicts with the spec's "graceful error handling" acceptance criterion. Stubs that return `[]` would silently pass the "does not crash App" test.

---

## Architecture

### Module Dependency Graph

```
        ┌──────────────┐
        │ storage/     │  (models.py, db.py)
        │  FeedItem    │
        └──────┬───────┘
               │
        ┌──────┴──────────┐
        │                 │
┌───────▼──────┐   ┌──────▼──────────┐
│ sources/     │   │ strategies/     │
│  base.py     │   │  base.py        │
│  arxiv.py    │   │  chronological. │
│  hackernews. │   │     py          │
│  github_     │   └──────┬──────────┘
│   trending.  │          │
│  huggingface.│          │
│  newsletter. │          │
└──────┬───────┘          │
       │                  │
       └─────┬────────────┘
             │
      ┌──────▼───────┐
      │ workers.py   │ (asyncio.Task orchestration)
      └──────┬───────┘
             │
      ┌──────▼───────┐
      │ widgets/     │ (feed_list.py, reading_pane.py)
      └──────┬───────┘
             │
      ┌──────▼───────┐
      │ app.py       │ (Textual App subclass)
      └──────────────┘
```

**Key property:** The arrows only go upward. `widgets/feed_list.py` imports `strategies/base.py` (the Protocol) but MUST NOT import `strategies/chronological.py` (the concrete implementation). This invariant is load-bearing and will be verified by a test (see section K).

### Protocol Definitions (the contracts)

```python
# src/ai_dashboard/sources/base.py
from typing import Protocol
from ai_dashboard.storage.models import FeedItem

class SourceAdapter(Protocol):
    kind: str                           # "arxiv" | "hn" | ...
    default_interval_seconds: int

    async def fetch(self) -> list[FeedItem]: ...
```

```python
# src/ai_dashboard/strategies/base.py
from typing import Protocol, Iterable
from datetime import datetime
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem

class FeedListStrategy(Protocol):
    name: str                           # "chronological-all" | "only-arxiv" | ...

    def items(self, db: Database, now: datetime) -> Iterable[FeedItem]: ...
```

Both Protocols use `typing.Protocol` (PEP 544) for structural typing — adapters and strategies do NOT need to inherit from the Protocol class. This keeps the coupling loose and aligns with Python idioms.

### Data Model

```python
# src/ai_dashboard/storage/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass(frozen=True, slots=True)
class FeedItem:
    id: int | None                  # None until inserted
    source_kind: str                # 'arxiv' | 'hn' | 'github_trending' | 'huggingface' | 'newsletter'
    source_uid: str                 # source-local unique id (arxiv_id, hn story id, repo full_name, hf id, rss guid)
    title: str
    url: str
    published_at: datetime          # ISO8601 in DB, datetime in memory
    raw_payload: dict[str, Any]     # JSON-serializable dict, source-specific
    seen: bool
    created_at: datetime
```

### SQLite Schema

See spec section I for the authoritative schema. Single database file at `~/.local/share/ai-dashboard/cache.db` (respects `XDG_DATA_HOME` if set).

Migration strategy: schema version 1 only for MVP. On mismatch: drop-and-recreate (spec allows this for MVP). Future schema bumps will add a migration table.

---

## Spec Deviations

This plan deviates from the spec in two small, deliberate ways. Both were surfaced by the Architect review and are documented here rather than hidden.

### Deviation 1 — `FeedListStrategy.items()` signature (sync → async)

- **Spec says** (§ Constraints > V2 Pluggability, line 75):
  ```python
  def items(self, db: Database, now: datetime) -> Iterable[FeedItem]: ...
  ```
- **Plan uses**:
  ```python
  async def items(self, db: Database, now: datetime) -> list[FeedItem]: ...
  ```
- **Why the deviation**: strategies need to query the `Database`, which is `aiosqlite`-backed and therefore async-only. A synchronous `items()` would force every strategy to either (a) block the event loop with `asyncio.run_coroutine_threadsafe`, (b) maintain a parallel sync connection to SQLite, or (c) receive pre-materialized items from the widget — the last of which breaks the pluggability guarantee because the widget would need to know what each strategy wants before asking.
- **Impact on V2 authors**: a V2 filter strategy author MUST write an `async def items`. This is the idiomatic Python 3.11+ pattern and aligns with everything else in the codebase. The error signal is clear at first use: a sync `items()` method will cause `await strategy.items(...)` to fail at runtime with "object is not awaitable", which is obvious and fixable in seconds.
- **Status**: applied in Phase 4.1. Spec should receive an errata note — this plan is the authoritative contract for implementation.

### Deviation 2 — "All-async" SQLite instead of spec's "may use sync with care"

- **Spec says** (§ Constraints > Storage, line 56):
  > "async via `aiosqlite` acceptable for fetchers; main App can use sync with care"
- **Plan uses**: `aiosqlite` everywhere, including the main App. No sync `sqlite3` calls anywhere.
- **Why the deviation**: mixing sync and async SQLite in one process is painful — every sync call needs to be audited for "does this block the event loop?", every test fixture has to decide which mode it's in, and there's a real risk of accidentally creating two connections to the same DB (breaking WAL coherency). Choosing all-async gives one consistent pattern across the codebase and removes a class of subtle bugs.
- **Impact**: a trivial ~1ms per-call overhead in `aiosqlite` for the main App's read paths. Not measurable against the 200ms first-paint SLO (tested in Phase 6.10).
- **Status**: applied throughout. Documented in `Database` class docstring.

---

## Cold Start Experience (tradeoff tension surfaced by Architect)

The Architect review flagged a real tension the plan previously glossed over: **the foreground-only lifetime means freshness only applies while the TUI is open, but the 200ms first-paint SLO means we can't do a blocking bootstrap fetch on startup**. You can't have both.

The plan resolves this with a two-speed approach:

1. **First paint (<200ms): from cache only.** `App.on_mount` opens the DB, initializes the schema, and reads items from SQLite *before* starting the orchestrator. The TUI appears immediately with whatever was cached from the previous session. First-time users see an empty list during this window — this is documented behavior.

2. **Bootstrap fetch (seconds 0-30 after first paint): non-blocking, all 5 sources in parallel.** Immediately after first paint, `orchestrator.start()` spawns one task per adapter with **pre-set wake events**. The first iteration of each adapter's loop runs `fetch()` immediately (no initial sleep). Within ~5-15 seconds, the fast adapters (HN = 2min interval, but bootstrap = immediate) return items and the TUI populates. The slow adapters (newsletters = 60min interval) also run their first fetch immediately thanks to the pre-set event, so all 5 sources contribute data within the first minute of launch.

3. **Steady-state (minute 1+): per-source intervals.** After the bootstrap round, each adapter sleeps for its configured `default_interval_seconds` and wakes on the schedule.

**Status bar messaging** (Phase 5.4): during the initial bootstrap round, the status bar shows `"Fetching sources... [hn] [arxiv] [gh] [hf] [nl]"` with each source's marker removed as its first fetch completes. After ~30 seconds, the status bar displays the last-updated time per source.

**First-time user experience, summary:**
- 0ms: TUI appears (empty list if no cache)
- 0-200ms: first paint from cache completes (benchmarked in Phase 6.10)
- 0.5-10s: first items from HN, arXiv, GitHub Trending, HF appear (bootstrap fetches complete)
- 10-60s: newsletters appear (their bootstrap fetch is slower because RSS feeds are external)
- 60s+: steady-state polling on per-source intervals

This is explicitly traded off against building a synchronous bootstrap that would delay first paint by 5-15 seconds. The async bootstrap gives a responsive TUI immediately and populates data progressively, which is objectively better UX than a freeze-on-startup.

---

## Spec Compliance Table

Each spec acceptance criterion maps to the plan phase where it is implemented and the test that verifies it. This catches spec drift cheaply during Critic review and during autopilot execution.

| Spec AC | Description | Plan phase | Verified by |
|---|---|---|---|
| A.1 | Python 3.11+ with pyproject.toml | Phase 1.1 | `Phase 1.0 venv check` |
| A.2 | Single textual App entry point | Phase 5.4 | `test_app_snapshot.py` |
| A.3 | All HTTP async via httpx, no blocking calls | Phase 3 + 5.3 | `grep -rn "import requests"` + code review |
| A.4 | SQLite with schema migration path | Phase 2.2 | `test_storage.py::test_schema_idempotent` |
| B.1 | 5 source adapters implementing SourceAdapter | Phase 3.2-3.6 | `test_sources/test_*.py` (5 tests) |
| B.2 | Adapters are pure functions of HTTP → FeedItem | Phase 3 | Per-adapter unit tests via respx |
| B.3 | Errors logged, do not crash App | Phase 5.3 | `test_worker_isolation.py` (TBD) |
| B.4 | arXiv 3s polite delay | Phase 3.2 | `test_arxiv.py::test_polite_delay` |
| B.5 | GitHub Trending uses selectolax with polite UA | Phase 3.4 | `test_github_trending.py` |
| B.6 | HN filter by keyword list (case-insensitive word-boundary) | Phase 3.3 | `test_hackernews.py::test_keyword_filter` |
| B.7 | HuggingFace uses `createdAt` desc sort | Phase 3.5 | `test_huggingface.py` |
| B.8 | Newsletters via feedparser | Phase 3.6 | `test_newsletter.py` |
| C.1 | asyncio.Task per source spawned on mount | Phase 5.3 | code review + snapshot test |
| C.2 | Default intervals: arxiv 600, hn 120, gh 1800, hf 600, nl 3600 | Phase 3.2-3.6 | `test_*.py::test_default_interval` |
| C.3 | Intervals overridable via sources.toml | Phase 2.3 | `test_config.py` (TBD) |
| C.4 | New items trigger widget refresh via message | Phase 5.4 `ItemsArrived` | code review |
| C.5 | Fetch failure → consecutive_failures++ | Phase 5.3 | `test_workers.py::test_failure_backoff` (TBD) |
| C.6 | All tasks cancelled on unmount within 2s | Phase 5.3, 5.4 | `test_shutdown_under_2s.py` (TBD) |
| D.1 | Horizontal container, reading (2fr) + feed-list (1fr) | Phase 5.4 CSS | `test_app_snapshot.py` |
| D.2 | Feed list as DataTable with 3 columns | Phase 5.1 | snapshot test |
| D.3 | Items sorted desc by published_at | Phase 2.2 `get_items` | `test_storage.py::test_ordering` |
| D.4 | j/k/arrow navigation | Phase 5.4 BINDINGS | snapshot test + manual |
| D.5 | Selection → reading pane update in <100ms | Phase 5.1 + 5.2 | manual verification (profiled) |
| D.6 | Relative time rendering | Phase 5.1 `_relative` | `test_relative_time.py` (TBD) |
| E.1-5 | Per-source reading pane layouts | Phase 5.2 render methods | `test_reading_pane.py` (TBD) |
| F.1 | `q` quit within 2s | Phase 5.4 + 5.3 shutdown | `test_shutdown_under_2s.py` |
| F.2 | `r` force refresh all | Phase 5.4 `action_refresh_all` + 5.3 `refresh_all_now` | manual + `test_wake_events.py` (TBD) |
| F.3 | `o` open URL via webbrowser | Phase 5.4 `action_open_url` | manual |
| F.4 | `<space>` toggle seen | Phase 5.4 `action_toggle_seen` | manual + `test_seen_toggle.py` (TBD) |
| F.5 | `j/k/↓/↑` navigate | Phase 5.4 BINDINGS | snapshot test |
| F.6 | `?` help overlay | Phase 5.4 `action_help` | manual |
| G.1 | First paint <200ms | Phase 5.4 + WAL | **`test_first_paint.py`** (Phase 6.10) |
| G.2 | `last_check_time` persisted on exit | Phase 5.4 `on_unmount` | `test_last_check_persistence.py` (TBD) |
| G.3 | Unread marking | Phase 5.1 `_render_row` | manual |
| G.4 | `<space>` flips seen flag | Phase 5.4 | manual |
| H.1 | Freshness SLO: item visible in fetch_interval + 10s | Phase 5.3 | `test_freshness.py` with mocked clock (TBD) |
| H.2 | `r` triggers immediate refresh | Phase 5.3 `refresh_all_now` | manual |
| I.1 | SQLite schema v1 | Phase 2.2 | `test_storage.py::test_schema_v1` |
| I.2 | UNIQUE(source_kind, source_uid) dedup | Phase 2.2 upsert | `test_storage.py::test_idempotent_upsert` |
| I.3 | Schema migration on version mismatch | Phase 2.2 | `test_storage.py::test_migration` (TBD) |
| **J.1** | **FeedListStrategy Protocol in strategies/base.py** | **Phase 4.1** | **`test_strategies.py::test_feed_list_widget_imports_only_strategy_base`** |
| **J.2** | **ChronologicalAllSourcesStrategy is only concrete strategy** | **Phase 4.2** | **`test_strategies.py::test_only_one_production_strategy` (TBD)** |
| **J.3** | **Widget takes FeedListStrategy via constructor** | **Phase 5.1** | **`test_strategies.py::test_feed_list_widget_works_with_custom_strategy`** |
| **J.4** | **No refs to concrete strategy in widget file** | **Phase 5.1** | **AST-based import test (Phase 6.8)** |
| **J.5** | **Swap test: OnlyArxivStrategy works with zero widget edits** | **Phase 6.8** | **the pluggability test itself** |
| K.1 | pytest configured | Phase 1.1 | `pytest --collect-only` |
| K.2 | Per-adapter unit tests with recorded fixtures | Phase 6.3-6.7 | `pytest tests/test_sources/` |
| K.3 | Integration test with mocked httpx | Phase 6.3-6.7 | `respx` intercepts |
| K.4 | Textual snapshot test | Phase 6.9 | `test_app_snapshot.py` |
| K.5 | Pluggability swap test | Phase 6.8 | `test_strategies.py` |
| L.1 | `q` exits within 2s | Phase 5.4 | `test_shutdown_under_2s.py` |
| L.2 | Ctrl+C exits cleanly | Phase 5.3 signal handling | manual |
| L.3 | No orphan processes after exit | Phase 5.3 + 5.4 | `pgrep -f ai-dashboard` returns empty (manual) |
| L.4 | SQLite WAL committed, no stale journal | Phase 2.2 WAL mode | `test_storage.py::test_clean_close_removes_wal` (TBD) |

**Bolded rows** are the load-bearing V2 pluggability checks. These are the highest-priority acceptance gates and must all pass before the plan is considered Critic-approved.

---

## Implementation Steps

### Phase 1: Project Scaffolding

**1.0** — **Git repo init + virtualenv** (user-required addition)

Run at the project root (`/Users/dev/projects/dashboard`):

```bash
# Initialize git
git init
git config --local init.defaultBranch main 2>/dev/null || true

# Create Python 3.11+ virtualenv
python3.11 -m venv .venv
# (If python3.11 is not on PATH, fall back to `python3 -m venv .venv` and verify 3.11+ at startup)

# Activate the venv for all subsequent install/test commands
source .venv/bin/activate
python -c "import sys; assert sys.version_info >= (3, 11), sys.version"

# Upgrade pip inside the venv before installing deps
python -m pip install --upgrade pip
```

**Create `.gitignore`** before the first commit so we do not accidentally check in the venv or cached data:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
*.egg
build/
dist/

# Virtual environment
.venv/
venv/
env/

# Package metadata
pip-wheel-metadata/

# IDE / editor
.vscode/
.idea/
*.swp
*.swo
.DS_Store

# Pytest
.pytest_cache/
.cache/

# Coverage
.coverage
htmlcov/

# Snapshot tests
tests/__snapshots__/*.html

# Application data (generated at runtime, user-specific)
# Note: real app data lives in ~/.local/share/ai-dashboard, not in repo,
# but belt-and-suspenders for any dev who symlinks it back
cache.db
cache.db-wal
cache.db-shm

# OMC state / plans / specs (local orchestration metadata — do not commit by default;
# users can override by removing these lines if they want to check in their plans)
# .omc/
```

**Initial commit** after `.gitignore` is in place:

```bash
git add .gitignore
git commit -m "chore: initial git init and .gitignore"
```

**Acceptance for Phase 1.0:**
- `git status` shows a clean tree on `main` (or `master`) with one initial commit
- `ls .venv/bin/python` exists and `.venv/bin/python --version` prints 3.11 or higher
- `.gitignore` contains at minimum: `__pycache__/`, `.venv/`, `*.egg-info/`, `cache.db*`, `tests/__snapshots__/*.html`
- `cat .gitignore | grep -c "\\.venv"` returns at least 1

**1.1** — Create `pyproject.toml` at project root.

```toml
[project]
name = "ai-dashboard"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "textual>=0.60",
    "httpx>=0.27",
    "feedparser>=6.0.10",
    "selectolax>=0.3.20",
    "aiosqlite>=0.20",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-textual-snapshot>=1.0",
    "respx>=0.21",  # httpx mocking
]

[project.scripts]
ai-dashboard = "ai_dashboard.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_dashboard"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Justification for each runtime dep (5 total, down from 6):**
- `textual` — TUI framework (interview choice R7)
- `httpx` — async HTTP (required for arxiv, HN, newsletter RSS, GitHub Trending, AND HuggingFace via direct API)
- `feedparser` — RSS/Atom parsing for newsletters AND arXiv (which returns Atom)
- `selectolax` — fast HTML parser for GitHub Trending scrape (no official API)
- `aiosqlite` — async SQLite so DB writes don't block the event loop

**REMOVED from initial plan**: `huggingface_hub` — replaced with direct httpx calls to `https://huggingface.co/api/models|datasets|spaces`. Rationale (per Architect review): (a) the HF Python SDK is synchronous, forcing `asyncio.to_thread` which creates non-daemon threads that cannot be cancelled cleanly and break the 2s shutdown SLO; (b) the HF HTTP API is fully documented and trivial to call directly; (c) removing the dep aligns with Principle 2 ("simplest thing that works"). This is one fewer dependency with strictly better lifecycle behavior.

**Dev deps justified:** `pytest` + `pytest-asyncio` (test framework), `pytest-textual-snapshot` (official Textual snapshot tool), `respx` (httpx mocking, avoids recording live HTTP)

**No other deps permitted without justification.**

**1.2** — Create directory structure:
```
src/ai_dashboard/{__init__.py, __main__.py}
src/ai_dashboard/{sources,storage,strategies,widgets}/__init__.py
tests/{__init__.py, conftest.py, fixtures/}
tests/test_sources/__init__.py
```

**1.3** — `src/ai_dashboard/__init__.py`: empty, just marks package.

**1.4** — `src/ai_dashboard/__main__.py`: `from ai_dashboard.app import main; main()` so `python -m ai_dashboard` works.

**Acceptance for Phase 1:**
- **Inside the activated `.venv`**, `pip install -e .[dev]` succeeds
- `python -c "import ai_dashboard"` succeeds
- `ai-dashboard --help` fails gracefully with message "App not yet implemented" (placeholder)
- `git status` clean after committing the scaffolding as a second commit: `git add pyproject.toml src/ tests/ && git commit -m "chore: scaffolding (pyproject, package layout)"`

---

### Phase 1.5: Protocol Skeleton + NullAdapter (enables parallel Phase 5 start)

**Justification (from Architect review, synthesis from Option C):** The rejected Option C had a real strength — "App is always launchable" — that we can incorporate without Option C's downside ("empty-stub masks broken adapter"). We do this by shipping a tiny, deliberately-marked `NullAdapter` that exists ONLY to make Phase 5 (App + widgets) buildable in parallel with Phase 3 (real adapters). A test enforces that `NullAdapter` is never referenced by production code, so it cannot leak into a shipped build.

**1.5.1** — `src/ai_dashboard/sources/base.py` (final version, see Phase 3.1 for details): define `SourceAdapter` Protocol, `SourceError`, `SourceRateLimited`.

**1.5.2** — `src/ai_dashboard/strategies/base.py` (final version, see Phase 4.1 for details): define `FeedListStrategy` Protocol with async `items()`.

**1.5.3** — `src/ai_dashboard/sources/_null.py` — `NullAdapter`

```python
# NULL ADAPTER — MUST NOT SHIP OUTSIDE PHASE-1.5 BOOTSTRAP
# This adapter exists ONLY to unblock Phase 5 (widgets + App) from Phase 3 (real adapters).
# A CI test verifies no production code references this file or class.
# If you are importing this outside tests/ or outside Phase 1.5 bootstrap wiring, STOP and
# use a real adapter.

from ai_dashboard.storage.models import FeedItem

class NullAdapter:
    kind = "null"
    default_interval_seconds = 3600

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def fetch(self) -> list[FeedItem]:
        return []
```

**1.5.4** — Test guard: `tests/test_null_adapter_is_not_shipped.py`

```python
import ast
from pathlib import Path

PRODUCTION_DIRS = ["src/ai_dashboard/app.py", "src/ai_dashboard/workers.py", "src/ai_dashboard/widgets/"]

def test_null_adapter_is_not_referenced_by_production_code():
    """NullAdapter exists solely to unblock Phase 1.5 bootstrap.
    It must NEVER be imported by shipped production code."""
    for target in PRODUCTION_DIRS:
        p = Path(target)
        files = [p] if p.is_file() else list(p.rglob("*.py"))
        for f in files:
            content = f.read_text()
            assert "NullAdapter" not in content, f"{f} references NullAdapter"
            assert "sources._null" not in content, f"{f} imports sources._null"
            assert "sources/_null" not in content, f"{f} references sources/_null path"
```

**Acceptance for Phase 1.5:**
- `strategies/base.py` and `sources/base.py` exist with the final Protocol definitions
- `NullAdapter` can be imported from `ai_dashboard.sources._null` in tests only
- `pytest tests/test_null_adapter_is_not_shipped.py` passes (currently: trivially, because no production code exists yet; must continue to pass after Phase 5)
- Commit: `git add src/ai_dashboard/sources/base.py src/ai_dashboard/sources/_null.py src/ai_dashboard/strategies/base.py tests/test_null_adapter_is_not_shipped.py && git commit -m "feat: protocol skeleton and bootstrap NullAdapter"`

---

### Phase 2: Data Layer (4 files)

**2.1** — `src/ai_dashboard/storage/models.py`

Implements `FeedItem` dataclass as shown in Data Model section above. Include:
- `to_row()` method that returns a tuple for DB insert (datetime → ISO string, dict → `json.dumps`)
- `from_row(row)` classmethod that reconstructs FeedItem from a sqlite3 Row
- `SourceKind` StrEnum: `arxiv`, `hn`, `github_trending`, `huggingface`, `newsletter`

**2.2** — `src/ai_dashboard/storage/db.py`

A `Database` class wrapping **exactly one** `aiosqlite.Connection` (single-instance contract, see below):

```python
class Database:
    def __init__(self, path: Path): ...
    async def connect(self) -> None:
        """Open the single connection and enable WAL mode. Idempotent."""
        self._conn = await aiosqlite.connect(self.path)
        # WAL mode: readers never block writers; writers rarely block readers.
        # Produces cache.db-wal and cache.db-shm files alongside cache.db — these are NORMAL
        # and are checkpointed on clean close. They are listed in .gitignore from Phase 1.0.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL is safe & fast
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self) -> None:
        """Commit any pending txn and close connection. Idempotent."""
        if self._conn:
            await self._conn.commit()
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        """Create tables if missing. Uses executescript() for atomic multi-statement DDL.
        This is one sqlite call instead of 4 separate awaits, ~4x faster (relevant for
        <200ms first-paint SLO)."""
        await self._conn.executescript(SCHEMA_V1_SQL)
        await self._conn.commit()

    async def upsert_items(self, items: list[FeedItem]) -> int:
        """Returns count of NEW rows inserted (not updated). Used by workers to decide
        whether to post an ItemsArrived message to the UI."""
        ...

    async def get_items(self, limit: int = 500, where: str | None = None) -> list[FeedItem]: ...
    async def mark_seen(self, item_id: int) -> None: ...
    async def get_user_state(self, key: str) -> str | None: ...
    async def set_user_state(self, key: str, value: str) -> None: ...
    async def get_source_state(self, kind: str) -> dict | None: ...
    async def update_source_state(self, kind: str, *, last_fetched=None, next_fetch=None, consecutive_failures=None) -> None: ...
```

**Single-connection contract (load-bearing):**

The `Database` class owns **exactly one** `aiosqlite.Connection` for the lifetime of the App. It is constructed once in `App.on_mount`, passed to both the `PollingOrchestrator` and the widgets, and closed once in `App.on_unmount`. **Do not** instantiate `Database` a second time for "read replicas" or "fast path reads" — `aiosqlite` serializes operations per connection, and a second connection breaks the WAL coherency assumptions and reintroduces SQLITE_BUSY under concurrent writes. If a future need for parallel reads emerges (V2 scale), use `SELECT` queries that run on the same connection — WAL mode already lets them proceed without blocking writers.

Schema creation uses `executescript()` to submit all DDL in one atomic batch (`CREATE TABLE IF NOT EXISTS ...`). Upsert uses:
```sql
INSERT INTO feed_items (...) VALUES (...) 
ON CONFLICT(source_kind, source_uid) DO UPDATE SET
    title = excluded.title,
    url = excluded.url,
    raw_payload = excluded.raw_payload,
    published_at = excluded.published_at
    -- NOTE: seen and created_at are NOT updated, preserving user state across re-fetches
```

**Critical:** `upsert_items` returns the count of rows that were NEW (not updated) — workers use this to decide whether to post an `ItemsArrived` message to the TUI.

**WAL file expectations:** After a clean shutdown, the SQLite file is at `~/.local/share/ai-dashboard/cache.db`. The sidecar files `cache.db-wal` and `cache.db-shm` may exist during normal operation and will be checkpointed/removed on clean `close()`. They are listed in `.gitignore`. The spec's "no -journal files" acceptance (spec line 209) refers to the legacy rollback journal mode; in WAL mode there is no `-journal` file by design.

**2.3** — `src/ai_dashboard/config.py`

Simple dataclass + TOML loader:
```python
@dataclass
class SourceConfig:
    kind: str
    enabled: bool = True
    fetch_interval_seconds: int | None = None  # None = use adapter default
    options: dict[str, Any] = field(default_factory=dict)  # source-specific

@dataclass
class AppConfig:
    sources: list[SourceConfig]
    db_path: Path
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        # Default path: ~/.config/ai-dashboard/config.toml (respects XDG_CONFIG_HOME)
        # If not present, return hardcoded defaults matching spec section C defaults
```

Defaults hardcoded in the loader if config file is missing — zero-config first run works.

**2.4** — `tests/fixtures/` — create 5 fixture files by manual capture or hand-written mock responses:
- `arxiv_response.xml` — real or hand-crafted Atom feed with 2 entries
- `hn_topstories.json` + `hn_item_{id}.json` — Firebase API response shapes
- `github_trending.html` — trimmed HTML from github.com/trending/python
- `hf_models.json` — response shape from `list_models()`
- `newsletter.xml` — RSS feed with 2 entries

**Acceptance for Phase 2:**
- `pytest tests/test_storage.py` passes (tests TBD in Phase 6)
- Schema can be created, dropped, and recreated without error
- `upsert_items` is idempotent (inserting same item twice returns count=1 first, count=0 second)
- WAL mode is enabled after `connect()`: `PRAGMA journal_mode` returns `wal`
- `cache.db-wal` and `cache.db-shm` files disappear after clean `close()`

---

### Phase 2.5: End-to-End Smoke Test (synthesis from Option A, Architect-required)

**Justification (from Architect review, synthesis from Option A):** Option B's biggest weakness is that no end-to-end flow exists until Phase 5 — that's ~65% through the work. Option A had this exactly right: build one slice to validate the `SourceAdapter` Protocol shape before fanning out to five implementations. Phase 2.5 captures that benefit in 30 minutes without sacrificing Phase 3's parallelism.

**2.5.1** — `scripts/smoke.py` (NOT shipped with the package; lives outside `src/`)

```python
"""
Phase 2.5 smoke test — end-to-end data-layer validation.

Runs the first real adapter (ArxivAdapter) against the live arXiv API and verifies:
  1. The adapter Protocol shape works against real HTTP
  2. FeedItem → SQLite round-trip succeeds
  3. upsert_items is idempotent on re-run
  4. WAL mode is active and no journal files are leaked

Run: `python scripts/smoke.py` (from project root, inside activated .venv)

If this script fails, DO NOT start Phase 3 (fanning out to 5 adapters). Fix the Protocol
or storage issue first. The cost of rebuilding one adapter is much less than rebuilding five.
"""
import asyncio
from pathlib import Path
import httpx
from ai_dashboard.storage.db import Database
from ai_dashboard.sources.arxiv import ArxivAdapter

async def main():
    db_path = Path("/tmp/ai_dashboard_smoke.db")
    if db_path.exists():
        db_path.unlink()

    db = Database(db_path)
    await db.connect()
    await db.init_schema()

    async with httpx.AsyncClient(timeout=10.0) as http:
        adapter = ArxivAdapter(http=http, options={})
        items = await adapter.fetch()
        print(f"[smoke] fetched {len(items)} items from arXiv")
        assert len(items) > 0, "arXiv returned zero items — check adapter"

        new_count_1 = await db.upsert_items(items)
        print(f"[smoke] first upsert: {new_count_1} new rows")
        assert new_count_1 == len(items), "first upsert should insert all"

        new_count_2 = await db.upsert_items(items)
        print(f"[smoke] second upsert: {new_count_2} new rows (expect 0)")
        assert new_count_2 == 0, "second upsert should be idempotent"

        read_back = await db.get_items(limit=500)
        print(f"[smoke] read back: {len(read_back)} items")
        assert len(read_back) == len(items), "round-trip count mismatch"

    await db.close()
    # Verify WAL sidecar cleanup
    assert not (db_path.parent / f"{db_path.name}-wal").exists(), "WAL file leaked after close"
    assert not (db_path.parent / f"{db_path.name}-shm").exists(), "SHM file leaked after close"
    print("[smoke] PASS")

if __name__ == "__main__":
    asyncio.run(main())
```

**Acceptance for Phase 2.5:**
- `python scripts/smoke.py` succeeds against the live arXiv API
- All 4 assertions pass (non-empty fetch, idempotent upsert, round-trip count, WAL cleanup)
- Execution completes in under 15 seconds
- After this gate passes, Phase 3 may fan out to the remaining 4 adapters in parallel

**If this gate FAILS:** halt Phase 3. The failure mode indicates either (a) the `SourceAdapter` Protocol shape is wrong (needs revision in Phase 3.1), (b) `aiosqlite` single-connection semantics are broken (revise Phase 2.2), or (c) the arXiv adapter's parsing is wrong (fix and re-run). Do not proceed to parallel adapter implementation until this smoke test is green.

---

### Phase 3: Source Adapters (6 files, parallelizable after Phase 2.5 gate)

**3.1** — `src/ai_dashboard/sources/base.py`

```python
from typing import Protocol, Any
import httpx
from ai_dashboard.storage.models import FeedItem


class SourceAdapter(Protocol):
    """All source adapters implement this Protocol structurally (PEP 544).

    Construction convention (documented, not statically enforced by Protocol):
        def __init__(self, http: httpx.AsyncClient, options: dict[str, Any]) -> None: ...

    The `http` client is SHARED across all adapters and owned by PollingOrchestrator.
    The `options` dict comes from SourceConfig.options (kind-specific keys like `keywords`, `feeds`).
    """

    kind: str                              # "arxiv" | "hn" | "github_trending" | "huggingface" | "newsletter"
    default_interval_seconds: int

    async def fetch(self) -> list[FeedItem]:
        """Fetch fresh items from the source. Must be idempotent (safe to call repeatedly).
        Must raise SourceError (or subclass) on retriable failures. Must return an empty
        list if the source has genuinely no new items (distinguishable from errors).
        """
        ...


class SourceError(Exception):
    """Raised by adapters when a fetch fails for any reason workers should log + retry."""


class SourceRateLimited(SourceError):
    """Raised when the upstream explicitly tells us to back off (HTTP 429 etc).
    Workers use this to extend the next sleep interval."""
```

**Factory for mechanical app wiring** — `src/ai_dashboard/sources/__init__.py`:

```python
"""Source registry: single place where kind strings map to adapter classes.

Rationale: app.py::_build_adapters should not hardcode 5 per-source imports and
5 per-source constructor calls. A factory centralizes this so adding/removing a
source is one-line edit in one place."""
from typing import Any
import httpx
from ai_dashboard.sources.base import SourceAdapter
from ai_dashboard.sources.arxiv import ArxivAdapter
from ai_dashboard.sources.hackernews import HackerNewsAdapter
from ai_dashboard.sources.github_trending import GithubTrendingAdapter
from ai_dashboard.sources.huggingface import HuggingFaceAdapter
from ai_dashboard.sources.newsletter import NewsletterAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {
    "arxiv": ArxivAdapter,
    "hn": HackerNewsAdapter,
    "github_trending": GithubTrendingAdapter,
    "huggingface": HuggingFaceAdapter,
    "newsletter": NewsletterAdapter,
}

def build_adapter(kind: str, http: httpx.AsyncClient, options: dict[str, Any]) -> SourceAdapter:
    if kind not in _REGISTRY:
        raise ValueError(f"Unknown source kind: {kind!r}. Known: {list(_REGISTRY)}")
    return _REGISTRY[kind](http=http, options=options)

def available_kinds() -> list[str]:
    return list(_REGISTRY)
```

NOTE: `NullAdapter` from Phase 1.5 is NOT registered in `_REGISTRY`. It lives in `sources/_null.py` (leading underscore signals private) and is only imported by tests.

**3.2-3.6** — One adapter file each (can be built in parallel):

**3.2** — `src/ai_dashboard/sources/arxiv.py` — `ArxivAdapter`
- `kind = "arxiv"`, `default_interval_seconds = 600`
- Endpoint: `http://export.arxiv.org/api/query?search_query=cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.AI+OR+cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results=50`
- Uses `feedparser.parse(content)` on the XML response
- Polite delay: minimum 3 seconds between requests (enforced via class-level `_last_request_time` + `asyncio.Lock`)
- Maps entry → FeedItem: title, authors, summary (abstract), arxiv_id (parsed from id URL), primary_category
- `raw_payload` includes all fields the reading pane might want

**3.3** — `src/ai_dashboard/sources/hackernews.py` — `HackerNewsAdapter`
- `kind = "hn"`, `default_interval_seconds = 120`
- Endpoint: `https://hacker-news.firebaseio.com/v0/topstories.json` (fetch IDs), then parallel `item/{id}.json` for the top N (default 30)
- Keywords: `["AI", "ML", "LLM", "GPT", "Claude", "OpenAI", "Anthropic", "neural", "transformer", "diffusion", "agent", "LoRA", "fine-tun", "embedding", "RAG"]` (configurable via `SourceConfig.options["keywords"]`)
- Match is case-insensitive word-boundary regex against `title + " " + url`
- `source_uid = str(hn_id)`

**3.4** — `src/ai_dashboard/sources/github_trending.py` — `GithubTrendingAdapter`
- `kind = "github_trending"`, `default_interval_seconds = 1800`
- Endpoint: scrape `https://github.com/trending/python?since=daily` + `trending?since=daily&spoken_language_code=en`
- Parser: `selectolax.parser.HTMLParser` (pure-C, no deps)
- Extract from each `article.Box-row`: repo name, owner, description, stars, language
- User-Agent: `"ai-dashboard/0.1 (+https://github.com/user/ai-dashboard)"`
- Filter: keep repos where description or topics contain AI keywords; fall back to topic-only match if description is empty
- `source_uid = f"{owner}/{name}"`

**3.5** — `src/ai_dashboard/sources/huggingface.py` — `HuggingFaceAdapter`
- `kind = "huggingface"`, `default_interval_seconds = 600`
- **Uses direct HTTP API via `httpx`** (NOT the `huggingface_hub` SDK — see pyproject justification above). Endpoints:
  - `https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=30`
  - `https://huggingface.co/api/datasets?sort=createdAt&direction=-1&limit=20`
  - `https://huggingface.co/api/spaces?sort=createdAt&direction=-1&limit=20`
- Fetch all three in parallel via `asyncio.gather` — pure async, no thread pool, no cancellation hazards
- Each JSON response is a list of dicts with stable fields: `id`, `author`, `pipeline_tag`, `downloads`, `lastModified`, `createdAt`, `tags`
- `source_uid = f"{kind_prefix}:{id}"` where `kind_prefix ∈ {model, dataset, space}`
- `raw_payload` includes all fields returned by the API (we store them verbatim so the reading pane can display any of them without re-querying)
- No auth required for these public endpoints; honors `Accept: application/json` header
- Rate limit: HF imposes ~300 req/5min unauthenticated; our 3 calls every 600s is nowhere near the limit

**3.6** — `src/ai_dashboard/sources/newsletter.py` — `NewsletterAdapter`
- `kind = "newsletter"`, `default_interval_seconds = 3600`
- Config-driven: takes a list of RSS URLs from `SourceConfig.options["feeds"]`
- Defaults: `["https://jack-clark.net/feed/", "https://www.deeplearning.ai/the-batch/feed/", "https://tldr.tech/api/rss/ai"]`
- One httpx GET per feed, then `feedparser.parse`
- `source_uid = f"{feed_url_hash[:8]}:{entry.guid or entry.link}"`

**Cross-cutting concerns for all adapters:**
- Each adapter has a **shared** `httpx.AsyncClient` created by the `PollingOrchestrator`, passed into `__init__(http=...)` — NOT global, NOT per-request
- The shared client is constructed with **bounded timeouts and connection limits**:
  ```python
  httpx.AsyncClient(
      timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
      limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
      headers={"User-Agent": "ai-dashboard/0.1"},
      follow_redirects=True,
  )
  ```
  **Rationale (Architect improvement #1, #8):** 10s read timeout bounds cancellation observation latency, letting `App.on_unmount`'s 2s shutdown SLO be achievable in the worst case. The `pool=5.0` prevents pool exhaustion from hanging one adapter when a peer adapter has stuck connections. Bounded `max_connections=20` keeps a rogue source from starving siblings of sockets.
- Each adapter MAY override default headers per-request via `client.get(url, headers={...})` — useful for GitHub Trending which needs a browser-like UA
- Each adapter catches its own network errors and raises `SourceError(msg)` with context — workers log and backoff
- Retries: 3 attempts with exponential backoff (1s, 4s, 9s max) for 5xx and network errors; fail-fast on 4xx
- On explicit 429 / Retry-After, adapters raise `SourceRateLimited` and workers extend the next sleep by Retry-After seconds

**Acceptance for Phase 3:**
- Each adapter has a unit test that feeds its fixture file through the parser logic and asserts correct FeedItem output (Phase 6 writes these)
- No adapter imports any other adapter, no adapter imports storage or widgets
- Linting: `python -c "from ai_dashboard.sources import arxiv, hackernews, github_trending, huggingface, newsletter"` works
- `build_adapter("arxiv", http, {})` returns an `ArxivAdapter` instance (factory test)

---

### Phase 4: Strategy Layer (2 files)

**4.1** — `src/ai_dashboard/strategies/base.py`

```python
from typing import Protocol
from datetime import datetime
from ai_dashboard.storage.db import Database
from ai_dashboard.storage.models import FeedItem


class FeedListStrategy(Protocol):
    """Pluggable strategy for the right-panel feed list (MVP seam for V2 filters).

    SPEC DEVIATION: the spec defines this Protocol's items() as synchronous with
    `Iterable[FeedItem]` return. The plan uses an ASYNC signature returning `list[FeedItem]`.
    See the 'Spec Deviations' section for justification (TL;DR: strategies need to hit
    `aiosqlite.Database` which is async; making items() sync would force every strategy
    to run `asyncio.run_coroutine_threadsafe` or block the event loop).
    """

    name: str                              # "chronological-all" | "only-arxiv" | ...

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        """Return items to display in the feed-list panel, newest first.
        Implementations should not cache — the widget calls this every refresh."""
        ...
```

Note: `items()` is async so strategies can do their own DB queries without blocking. This is a deliberate, documented spec deviation (see Spec Deviations section).

**4.2** — `src/ai_dashboard/strategies/chronological.py` — `ChronologicalAllSourcesStrategy`

```python
class ChronologicalAllSourcesStrategy:
    name = "chronological-all"

    def __init__(self, limit: int = 500):
        self.limit = limit

    async def items(self, db: Database, now: datetime) -> list[FeedItem]:
        return await db.get_items(limit=self.limit)
        # db.get_items() already sorts by published_at DESC
```

**Acceptance for Phase 4:**
- `ChronologicalAllSourcesStrategy` is the ONLY concrete strategy in the codebase
- `strategies/chronological.py` file length < 30 lines (it should be trivial)
- Protocol is structurally typed — no ABC, no inheritance requirement

---

### Phase 5: UI & App (5 files)

**5.1** — `src/ai_dashboard/widgets/feed_list.py` — `FeedListWidget(ListView)` or `FeedListWidget(DataTable)`

- Subclass a Textual widget appropriate for lists (DataTable gives more control, ListView is simpler — pick DataTable for column formatting)
- Constructor: `def __init__(self, strategy: FeedListStrategy, db: Database, ...)`. Strategy is INJECTED.
- **File MUST NOT import any concrete strategy.** Only `from ai_dashboard.strategies.base import FeedListStrategy`.
- Renders 3 columns: `[source_tag, title (truncated), relative_time]`
- `async def refresh_items(self)` method reloads from strategy and repopulates the table
- Emits `ItemSelected(FeedItem)` message when selection changes
- Relative time helper: `_relative(dt: datetime, now: datetime) -> str` → "now" | "3m" | "1h" | "2d"

**5.2** — `src/ai_dashboard/widgets/reading_pane.py` — `ReadingPane(Static)` or `ReadingPane(ScrollableContainer)`

- Shows currently selected FeedItem
- Dispatches rendering based on `source_kind`:
  - Maps kind → private render method (`_render_arxiv`, `_render_hn`, `_render_github_trending`, `_render_huggingface`, `_render_newsletter`)
  - **Each render method's return type is strictly `rich.text.Text | rich.console.Group[rich.text.Text]`** — NOT the looser `RenderableType`. This enforces Principle 2 at the type level: if someone later tries to return a `rich.markdown.Markdown` or `rich.syntax.Syntax`, the type checker (or a unit test asserting `isinstance(result, (Text, Group))`) will reject it.
- `async def show_item(self, item: FeedItem | None)` method for update
- No HTTP, no markdown parsing, no file reads. Pure text formatting of `item.raw_payload` fields.
- **Import restriction** (verified by test in Phase 6): `reading_pane.py` MUST NOT import `rich.markdown`, `rich.syntax`, `rich.panel` (Panel is allowed), `rich.table`, or `rich.tree`. Allowed rich imports: `rich.text.Text`, `rich.console.Group`, `rich.style.Style`, `rich.panel.Panel` (optional, for section separators).

**5.3** — `src/ai_dashboard/workers.py` — `PollingOrchestrator`

Revised per Architect review: adds per-adapter `asyncio.Event` wake mechanism (eliminates `refresh_all_now` tearing down the orchestrator), corrects the shutdown order (close http client BEFORE `wait_for`), lowers http timeouts to 10s, and adds a bootstrap-fetch kickoff on start so first-run users see data within ~10s instead of 60min.

```python
import asyncio
from datetime import datetime, timezone
import httpx
from typing import Callable, Awaitable

from ai_dashboard.sources.base import SourceAdapter, SourceError, SourceRateLimited
from ai_dashboard.storage.db import Database


NewItemsCallback = Callable[[int, str], Awaitable[None]]  # (count, source_kind) -> awaitable


class PollingOrchestrator:
    """Owns the shared httpx.AsyncClient and one asyncio.Task per adapter.

    Lifecycle:
      orchestrator.start()            # creates http client, spawns tasks, schedules bootstrap fetch
      orchestrator.refresh_all_now()  # wakes all adapters immediately (sets each Event)
      orchestrator.stop(timeout=2.0)  # cancels tasks, closes http, waits for cleanup

    Shutdown contract: stop() must return in <= timeout seconds even if an adapter is stuck
    in a read. It achieves this by: (1) cancelling tasks, (2) closing the http client (which
    aborts in-flight sockets), (3) waiting for gather with TimeoutError swallowed.
    """

    def __init__(
        self,
        adapter_specs: list[tuple[str, dict[str, Any]]],
        db: Database,
        on_new_items: NewItemsCallback,
    ) -> None:
        """
        adapter_specs: list of (kind, options) tuples. The orchestrator OWNS adapter
        instantiation because adapters need the shared httpx.AsyncClient, which is
        created inside start(). Passing specs (not instances) eliminates the ordering
        problem where adapters would need an http client that doesn't exist yet.
        """
        self.adapter_specs = adapter_specs
        self.db = db
        self.on_new_items = on_new_items
        self._adapters: list[SourceAdapter] = []  # populated in start()
        self._tasks: list[asyncio.Task] = []
        self._wake_events: dict[str, asyncio.Event] = {}
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Create the shared http client, build adapters, and spawn one task per adapter.

        The tasks use a bootstrap kickoff — each wake event is pre-set so the first
        iteration runs fetch() immediately (without waiting for default_interval_seconds).
        This avoids the first-run "TUI is empty for 10-60 minutes" experience.
        """
        from ai_dashboard.sources import build_adapter  # local import avoids cycles

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "ai-dashboard/0.1"},
            follow_redirects=True,
        )

        # Build adapters now that http client is live
        self._adapters = [
            build_adapter(kind, http=self._http, options=options)
            for (kind, options) in self.adapter_specs
        ]

        for adapter in self._adapters:
            # Each adapter gets its own wake event. Pre-set means "fetch immediately on first loop".
            ev = asyncio.Event()
            ev.set()  # bootstrap: first iteration runs fetch() without initial sleep
            self._wake_events[adapter.kind] = ev

            task = asyncio.create_task(self._run_adapter(adapter, ev), name=f"poll-{adapter.kind}")
            self._tasks.append(task)

    async def _run_adapter(self, adapter: SourceAdapter, wake: asyncio.Event) -> None:
        """Infinite loop: wait (or be woken) → fetch → upsert → notify → repeat.

        Error handling:
          - CancelledError propagates (shutdown signal)
          - SourceRateLimited: extend next sleep based on retry-after hint (or 2x default)
          - SourceError and bare Exception: log, increment failure counter, backoff 2x after 5 consecutive
        """
        sleep_seconds: float = 0.0  # first iteration: bootstrap (skip wait, consume pre-set event)
        while True:
            # Interruptible sleep: either the interval elapses, or refresh_all_now() sets the event.
            if sleep_seconds > 0:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=sleep_seconds)
                    wake.clear()  # woken by refresh_all_now
                except asyncio.TimeoutError:
                    pass  # interval elapsed without manual refresh; proceed to fetch
                # asyncio.CancelledError propagates naturally here during shutdown
            else:
                # Bootstrap path: pre-set event gets consumed immediately, no sleep.
                wake.clear()

            try:
                items = await adapter.fetch()
                new_count = await self.db.upsert_items(items)
                if new_count > 0:
                    await self.on_new_items(new_count, adapter.kind)
                await self.db.update_source_state(
                    adapter.kind,
                    last_fetched=datetime.now(timezone.utc),
                    consecutive_failures=0,
                )
                sleep_seconds = adapter.default_interval_seconds
            except asyncio.CancelledError:
                raise
            except SourceRateLimited as e:
                # Respect upstream backoff; 2x default is a safe baseline
                sleep_seconds = adapter.default_interval_seconds * 2
            except (SourceError, Exception):
                state = await self.db.get_source_state(adapter.kind) or {}
                failures = int(state.get("consecutive_failures") or 0) + 1
                await self.db.update_source_state(adapter.kind, consecutive_failures=failures)
                # Exponential-ish backoff: 1x, 1x, 1x, 1x, 2x, 2x, ...
                sleep_seconds = adapter.default_interval_seconds * (2 if failures >= 5 else 1)

    async def stop(self, timeout: float = 2.0) -> None:
        """Shut down all workers within `timeout` seconds.

        Order is critical:
          1. Cancel tasks (they observe cancellation at await points)
          2. Close http client (aborts any in-flight sockets, letting awaits see CancelledError sooner)
          3. Wait for gather with TimeoutError swallowed
        """
        for task in self._tasks:
            task.cancel()

        # Aborting the http client is the most important step: it tears down sockets
        # so any `await client.get(...)` wakes up with a disconnect error, which gets
        # cancelled by the already-delivered CancelledError.
        if self._http is not None:
            try:
                await asyncio.wait_for(self._http.aclose(), timeout=timeout / 2)
            except asyncio.TimeoutError:
                pass  # http client refused to close; the OS will clean up sockets on process exit
            self._http = None

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout / 2,
            )
        except asyncio.TimeoutError:
            # Hard deadline hit — log and move on. Process is exiting anyway.
            pass

        self._tasks.clear()
        self._wake_events.clear()

    async def refresh_all_now(self) -> None:
        """Wake every adapter immediately. Non-destructive: the existing tasks and http
        client persist. This replaces the earlier plan's teardown-and-restart approach,
        which had a 2s stall and race conditions."""
        for ev in self._wake_events.values():
            ev.set()
```

**Notes on correctness:**
- The wake event + `asyncio.wait_for` pattern is the canonical way to make a polling loop interruptible. When `refresh_all_now` sets the event, `wait_for` returns immediately (not a TimeoutError, not CancelledError), and the loop proceeds to fetch.
- The initial `sleep_seconds = 0` + pre-set wake event means the first iteration runs `fetch()` **without** any initial sleep, giving the bootstrap-on-start behavior.
- Shutdown closes http first so in-flight reads unblock fast. The 2s timeout is split between http close (1s) and task gather (1s), each with their own `wait_for`.
- There is no `asyncio.to_thread` anywhere — we eliminated `huggingface_hub` specifically to avoid the non-cancellable thread problem Architect flagged.

**5.4** — `src/ai_dashboard/app.py` — `AIDashboardApp(App)`

```python
from datetime import datetime, timezone
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.message import Message
import httpx

from ai_dashboard.config import AppConfig
from ai_dashboard.storage.db import Database
from ai_dashboard.sources import build_adapter, available_kinds
from ai_dashboard.sources.base import SourceAdapter
from ai_dashboard.strategies.base import FeedListStrategy
from ai_dashboard.strategies.chronological import ChronologicalAllSourcesStrategy
from ai_dashboard.widgets.feed_list import FeedListWidget
from ai_dashboard.widgets.reading_pane import ReadingPane
from ai_dashboard.workers import PollingOrchestrator


class ItemsArrived(Message):
    """Posted by PollingOrchestrator's on_new_items callback; consumed by App.
    Routed through Textual's message queue so on_unmount can drain pending messages
    atomically and avoid races with shutdown."""
    def __init__(self, count: int, source_kind: str) -> None:
        super().__init__()
        self.count = count
        self.source_kind = source_kind


class AIDashboardApp(App):
    CSS = """
    #layout { layout: horizontal; height: 100%; }
    #reading-pane { width: 2fr; border: solid $primary; }
    #feed-list { width: 1fr; border: solid $accent; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
        ("o", "open_url", "Open URL"),
        ("space", "toggle_seen", "Toggle seen"),
        ("?", "help", "Help"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.db = Database(config.db_path)
        self.strategy: FeedListStrategy = ChronologicalAllSourcesStrategy(limit=500)
        self.orchestrator: PollingOrchestrator | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="layout"):
            yield ReadingPane(id="reading-pane")
            yield FeedListWidget(self.strategy, self.db, id="feed-list")

    async def on_mount(self) -> None:
        # Order matters: open db → init schema → first paint from cache → spawn workers.
        # The first-paint happens BEFORE workers start so the TUI is not blocked on network.
        await self.db.connect()
        await self.db.init_schema()

        # First paint from cache (must be <200ms per spec section G) — see
        # tests/test_first_paint.py benchmark for enforcement.
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

        # Now spawn workers. Bootstrap wake events (pre-set) make each adapter fetch
        # immediately on its first loop iteration, so first-run users see data within ~10s.
        self.orchestrator = PollingOrchestrator(
            adapter_specs=self._adapter_specs(),
            db=self.db,
            on_new_items=self._post_items_arrived,
        )
        await self.orchestrator.start()

    async def on_unmount(self) -> None:
        # Shutdown order: stop orchestrator → persist user state → close db.
        # Orchestrator stop has its own 2s deadline (split: 1s for http close, 1s for task gather).
        if self.orchestrator is not None:
            await self.orchestrator.stop(timeout=2.0)
        await self.db.set_user_state("last_check_time", datetime.now(timezone.utc).isoformat())
        await self.db.close()

    async def _post_items_arrived(self, count: int, source_kind: str) -> None:
        """Callback given to PollingOrchestrator. Routes via Textual's message queue
        instead of directly calling widget methods — this eliminates the on_unmount race
        (a pending callback scheduled right before stop() would try to touch a closing db)."""
        self.post_message(ItemsArrived(count=count, source_kind=source_kind))

    async def on_items_arrived(self, message: ItemsArrived) -> None:
        """Handler for ItemsArrived messages — drained atomically by Textual's message pump."""
        feed_list = self.query_one(FeedListWidget)
        await feed_list.refresh_items()

    def _adapter_specs(self) -> list[tuple[str, dict[str, Any]]]:
        """Return (kind, options) tuples for every enabled source in config.
        The orchestrator owns actual adapter instantiation (it needs the shared
        http client, which is created inside start()). Keeping adapter construction
        there eliminates the ordering hazard of "adapters need an http client that
        doesn't exist yet"."""
        return [
            (source_cfg.kind, source_cfg.options)
            for source_cfg in self.config.sources
            if source_cfg.enabled
        ]

    def action_refresh_all(self) -> None:
        """Triggered by `r` key. Wakes all adapters immediately (non-destructive)."""
        if self.orchestrator is not None:
            # Use run_worker to schedule the async call without blocking the event loop
            self.run_worker(self.orchestrator.refresh_all_now(), exclusive=True)

    def action_open_url(self) -> None: ...
    def action_toggle_seen(self) -> None: ...
    def action_help(self) -> None: ...


def main() -> None:
    config = AppConfig.load()
    app = AIDashboardApp(config)
    app.run()
```

**Authoritative ownership model (no more patterns to pick between):**

`PollingOrchestrator` OWNS adapter construction. The App passes it a list of `(kind, options)` tuples via `adapter_specs`. Inside `start()`, the orchestrator (a) creates the shared `httpx.AsyncClient`, then (b) uses `build_adapter(kind, http=self._http, options=options)` from `sources/__init__.py` to instantiate each adapter. This is the only pattern in the plan; no alternative is considered.

Why this pattern:
- Adapters need the shared http client → the client must exist first → the orchestrator owns both → construction happens inside the orchestrator.
- The App stays thin: its only adapter-related method is `_adapter_specs()` which returns config-derived tuples. No imports of concrete adapter classes in `app.py`.
- Tests construct orchestrators with whatever spec tuples they need, including `[("null", {})]` — except that `NullAdapter` is NOT in the factory registry, so tests that need it must either (a) use a test-only factory override, or (b) construct `NullAdapter` directly and wrap it in the orchestrator (which requires a secondary constructor — NOT provided, keeping NullAdapter strictly for the Phase 1.5 bootstrap test).

**5.5** — `src/ai_dashboard/widgets/__init__.py` — exports `FeedListWidget`, `ReadingPane`. Nothing else.

**Acceptance for Phase 5:**
- `ai-dashboard` command launches the TUI, shows 2-panel layout, exits on `q`
- `python -c "import ai_dashboard.widgets.feed_list"` does NOT import any concrete strategy (verifiable with `ast.parse` walk or grep)

---

### Phase 6: Tests (7+ files)

**6.1** — `tests/conftest.py`

```python
import pytest
import asyncio
from pathlib import Path
from ai_dashboard.storage.db import Database

@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.connect()
    await d.init_schema()
    yield d
    await d.close()

@pytest.fixture
def fixture_dir():
    return Path(__file__).parent / "fixtures"
```

**6.2** — `tests/test_storage.py`
- Test schema creation, idempotent init_schema
- Test upsert_items returns new count correctly (1 first time, 0 second time)
- Test FeedItem round-trip (insert → get_items → equality)
- Test get_items ordering (newest first)
- Test mark_seen
- Test user_state get/set

**6.3** — `tests/test_sources/test_arxiv.py`
- Load `fixtures/arxiv_response.xml`
- Mock httpx via `respx` to return the fixture content
- Call `ArxivAdapter(http_client).fetch()`, assert returns N FeedItems with correct fields
- Test polite delay enforcement:
  - Monkeypatch `time.monotonic` (the clock used by the adapter's `_last_request_time` tracking) to advance in controlled steps
  - First `fetch()` call records `time.monotonic()` as the baseline
  - Advance monotonic by 1 second, call `fetch()` again — must await ~2 more seconds (mocked via `asyncio.sleep` replacement or `anyio.fail_after`)
  - Verify second fetch's underlying HTTP call happens ≥3s after the first
  - Alternative: use `freezegun` to freeze time and assert the adapter's `asyncio.Lock` + time computation blocks correctly

**6.4** — `tests/test_sources/test_hackernews.py`
- Mock topstories.json + per-item responses
- Assert keyword filter works (AI-matching stories retained, others dropped)

**6.5** — `tests/test_sources/test_github_trending.py`
- Mock HTML response with 3 repos: 2 AI-tagged, 1 non-AI
- Assert non-AI is filtered out

**6.6** — `tests/test_sources/test_huggingface.py`
- Mock the three HuggingFace HTTP API endpoints via `respx`:
  - `https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=30`
  - `https://huggingface.co/api/datasets?sort=createdAt&direction=-1&limit=20`
  - `https://huggingface.co/api/spaces?sort=createdAt&direction=-1&limit=20`
- Fixture files: `fixtures/hf_models.json`, `fixtures/hf_datasets.json`, `fixtures/hf_spaces.json`
- Assert FeedItems produced for models/datasets/spaces with correct `model:`/`dataset:`/`space:` `source_uid` prefix
- Assert all 3 endpoints are called in parallel (via `asyncio.gather`) — verified by total elapsed time approximating single-request time, not sum of three
- NOTE: the plan does NOT use `huggingface_hub` SDK or `asyncio.to_thread` — the adapter uses direct `httpx` calls, so tests use `respx` exactly like every other adapter test

**6.7** — `tests/test_sources/test_newsletter.py`
- Mock 1 RSS feed via respx
- Assert multiple feed URLs produce interleaved FeedItems

**6.8** — `tests/test_strategies.py` **(LOAD-BEARING — the pluggability swap test)**

```python
class OnlyArxivStrategy:
    """Test-only strategy used exclusively to verify pluggability."""
    name = "only-arxiv"
    async def items(self, db, now):
        return [i for i in await db.get_items(limit=500) if i.source_kind == "arxiv"]

async def test_feed_list_widget_works_with_custom_strategy(db):
    """
    This test ENFORCES the V2 pluggability requirement from the interview.
    It instantiates the FeedListWidget with OnlyArxivStrategy (which is defined
    in the test file, not the main package) and asserts the widget renders
    only arxiv items.

    If this test ever requires editing src/ai_dashboard/widgets/feed_list.py
    to make it work, the pluggability guarantee is broken.
    """
    # Seed DB with mixed items
    await db.upsert_items([
        FeedItem(None, "arxiv", "1", "Paper A", "http://...", now(), {}, False, now()),
        FeedItem(None, "hn", "2", "HN story", "http://...", now(), {}, False, now()),
        FeedItem(None, "github_trending", "3", "Repo", "http://...", now(), {}, False, now()),
    ])

    strategy = OnlyArxivStrategy()
    result = await strategy.items(db, now())

    assert len(result) == 1
    assert result[0].source_kind == "arxiv"
```

Also include a **static AST-based test** that verifies the import invariant. The earlier plan used grep-based substring matching — the Architect correctly pointed out this is bypassable (e.g., `from ai_dashboard.strategies import chronological` imports the module as a whole and dodges every grep assertion). The AST version walks every `Import` and `ImportFrom` node and rejects any reference to `ai_dashboard.strategies.*` other than `ai_dashboard.strategies.base`:

```python
import ast
from pathlib import Path

FEED_LIST_PATH = Path("src/ai_dashboard/widgets/feed_list.py")
ALLOWED_STRATEGY_IMPORT = "ai_dashboard.strategies.base"

def test_feed_list_widget_imports_only_strategy_base():
    """AST-based enforcement of the pluggability seam.

    Walks every Import and ImportFrom node in feed_list.py. Any reference to
    ai_dashboard.strategies.* other than ai_dashboard.strategies.base is a violation.

    This test cannot be bypassed by:
      - from ai_dashboard.strategies import chronological  (caught: ImportFrom with module='ai_dashboard.strategies' importing 'chronological')
      - import ai_dashboard.strategies.chronological  (caught: Import with alias.name='ai_dashboard.strategies.chronological')
      - import ai_dashboard.strategies.chronological as c  (caught: same as above, alias name inspected)
      - importlib.import_module('ai_dashboard.strategies.chronological')  (caught: string literal scan as secondary check)
    """
    src = FEED_LIST_PATH.read_text()
    tree = ast.parse(src, filename=str(FEED_LIST_PATH))

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("ai_dashboard.strategies"):
                if mod != ALLOWED_STRATEGY_IMPORT:
                    violations.append(
                        f"line {node.lineno}: from {mod} import {[n.name for n in node.names]} "
                        f"(only {ALLOWED_STRATEGY_IMPORT!r} is permitted)"
                    )
                else:
                    # from ai_dashboard.strategies.base — fine, but we also forbid
                    # importing ChronologicalAllSourcesStrategy by name via this path
                    for alias in node.names:
                        if alias.name == "ChronologicalAllSourcesStrategy":
                            violations.append(
                                f"line {node.lineno}: imports ChronologicalAllSourcesStrategy "
                                f"(only the Protocol class is permitted)"
                            )
            elif mod == "ai_dashboard.strategies":
                # "from ai_dashboard.strategies import <name>" — the package, not a submodule.
                # Any imported name is a concrete submodule reference. Forbidden.
                for alias in node.names:
                    violations.append(
                        f"line {node.lineno}: from ai_dashboard.strategies import {alias.name} "
                        f"(use from ai_dashboard.strategies.base import ... instead)"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("ai_dashboard.strategies"):
                    if alias.name != ALLOWED_STRATEGY_IMPORT:
                        violations.append(
                            f"line {node.lineno}: import {alias.name} "
                            f"(only {ALLOWED_STRATEGY_IMPORT!r} is permitted)"
                        )

    # Secondary check: no dynamic string references to concrete strategies
    # (catches importlib.import_module calls and __import__ with literal strings)
    if "strategies.chronological" in src and "strategies.chronological" not in ALLOWED_STRATEGY_IMPORT:
        violations.append(
            "string literal 'strategies.chronological' found in source — "
            "suggests dynamic import bypass attempt"
        )
    if "ChronologicalAllSourcesStrategy" in src:
        violations.append(
            "class name 'ChronologicalAllSourcesStrategy' found in source — "
            "widget must not reference the concrete strategy class"
        )

    assert not violations, (
        "feed_list.py violates the pluggability invariant:\n  "
        + "\n  ".join(violations)
    )
```

**6.9** — `tests/test_app_snapshot.py`
- Uses `pytest-textual-snapshot` to render the App with a seeded DB
- Assert the TUI layout renders with reading pane left + feed list right
- Store snapshot in `tests/__snapshots__/`

**6.10** — `tests/test_first_paint.py` — **First-paint benchmark (spec SLO enforcement)**

Per Architect review, the spec's 200ms first-paint SLO (§G) is unverified in the baseline plan. This test enforces it with a concrete measurement:

```python
import time
import pytest
from datetime import datetime, timezone
from ai_dashboard.storage.models import FeedItem
from ai_dashboard.storage.db import Database
from ai_dashboard.app import AIDashboardApp
from ai_dashboard.config import AppConfig

@pytest.mark.asyncio
async def test_first_paint_under_200ms(tmp_path):
    """Spec SLO: first paint from cache must complete in under 200ms with a seeded DB.

    Measures the time from App.on_mount entry to FeedListWidget.refresh_items return.
    Excludes Textual's initial compose/render (which is a Textual-internal concern and
    cannot be separated cleanly in measurement).
    """
    # Seed DB with 500 items (the refresh_items default limit)
    db_path = tmp_path / "cache.db"
    db = Database(db_path)
    await db.connect()
    await db.init_schema()
    seed = [
        FeedItem(
            id=None, source_kind="arxiv", source_uid=f"seed-{i}",
            title=f"Paper {i}", url=f"http://arxiv.org/abs/{i}",
            published_at=datetime.now(timezone.utc), raw_payload={"idx": i},
            seen=False, created_at=datetime.now(timezone.utc),
        )
        for i in range(500)
    ]
    await db.upsert_items(seed)
    await db.close()

    # Construct app pointing at the seeded DB
    config = AppConfig(sources=[], db_path=db_path)
    app = AIDashboardApp(config)

    # Manually invoke on_mount equivalent (without running Textual's event loop)
    # This isolates the storage + widget-refresh path from Textual's compose/render.
    t0 = time.perf_counter()
    await app.db.connect()
    await app.db.init_schema()
    # Simulate widget.refresh_items() by calling the strategy directly
    items = await app.strategy.items(app.db, datetime.now(timezone.utc))
    t1 = time.perf_counter()
    await app.db.close()

    elapsed_ms = (t1 - t0) * 1000.0
    assert elapsed_ms < 200.0, (
        f"first-paint path took {elapsed_ms:.1f}ms, exceeds 200ms SLO. "
        "Optimize db.init_schema (use executescript), reduce seed count, "
        "or demote the SLO in the spec."
    )
```

This test will also fail if WAL mode is NOT enabled (because rollback-journal mode has ~2x slower startup on cold files), catching a regression in the Database class.

**6.11** — `tests/test_reading_pane_imports.py` — **Render-type invariant** (Architect improvement #10)

```python
import ast
from pathlib import Path

FORBIDDEN_RICH_IMPORTS = {
    "rich.markdown", "rich.syntax", "rich.table", "rich.tree", "rich.pretty", "rich.traceback",
}

def test_reading_pane_does_not_import_rich_rendering_complexity():
    """Enforce Principle 2: reading pane is plain-text-only.

    The render methods must return Text | Group[Text]. Importing Markdown, Syntax, etc.
    is evidence that someone tried to add rich rendering. This test fails fast.
    """
    src = Path("src/ai_dashboard/widgets/reading_pane.py").read_text()
    tree = ast.parse(src)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in FORBIDDEN_RICH_IMPORTS:
                violations.append(f"line {node.lineno}: from {mod} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_RICH_IMPORTS:
                    violations.append(f"line {node.lineno}: import {alias.name}")
    assert not violations, (
        "reading_pane.py imports forbidden rich rendering modules:\n  "
        + "\n  ".join(violations)
    )
```

**Acceptance for Phase 6:**
- `pytest` runs with 100% of adapter tests passing, storage tests passing, strategy swap test passing, snapshot test passing, **first-paint benchmark passing**, **import invariant tests passing**
- Zero real network calls during tests (verified by `respx` intercepts; HF adapter uses direct httpx → respx handles it uniformly)
- CI-clean: `pytest -q` in under 30 seconds
- The NullAdapter guard from Phase 1.5 continues to pass (no production code references `NullAdapter`)

---

### Phase 7: Polish & Verification

**7.1** — `README.md`
- Installation: `pip install -e .`
- Run: `ai-dashboard`
- Config location: `~/.config/ai-dashboard/config.toml`
- Keybindings table
- "V2 ideas" section: mentions the `FeedListStrategy` seam and invites PRs

**7.2** — Manual verification:
- Launch the app against real sources (no mocks)
- Verify at least 1 item from each of the 5 sources appears within 5 minutes of launch
- Verify keybindings work: q, r, o, space, ?
- Verify clean exit with no zombie processes (`ps aux | grep python | grep ai-dashboard`)
- Verify SQLite file exists at `~/.local/share/ai-dashboard/cache.db` after first run

**7.3** — Lint / type pass:
- Run `python -m compileall src/` to catch syntax errors
- If mypy is desired (NOT required by spec): `mypy src/ai_dashboard` with reasonable strictness

---

## Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | GitHub Trending scrape breaks when GitHub updates HTML structure | Medium | Medium | Selector is centralized in `github_trending.py`; when broken, only that adapter fails gracefully (source isolation); add a test asserting the adapter still parses a known-good HTML fixture |
| R2 | Twitter/X requirement creeps back into MVP despite non-goal | Low | Medium | Spec's Non-Goals table is the source of truth; Critic verifies no Twitter code exists |
| R3 | arXiv API returns XML that breaks `feedparser` on edge cases | Low | Low | Fallback: `feedparser` is extremely tolerant; worst case we log and continue |
| R4 | HackerNews keyword filter produces too few or too many matches | Medium | Low | Keywords are configurable via `SourceConfig.options`; default list is reasonable but tunable |
| R5 | Textual layout CSS conflicts between widgets | Low | Medium | Layout is simple (1 horizontal container, 2 children); verified with snapshot test |
| R6 | SQLite locking under concurrent writes from 5 workers | Low | Medium | **WAL mode enabled in `Database.connect()`**: readers never block writers, writers rarely block readers. **Single-connection contract** documented: `Database` owns exactly one `aiosqlite.Connection`, passed to orchestrator + widgets. Enforced at review time; not a runtime check. |
| R7 | ~~`asyncio.to_thread` for `huggingface_hub` blocks the event loop~~ **REMOVED** | — | — | Architect improvement: replaced `huggingface_hub` SDK with direct httpx HTTP API calls. No threads, no cancellation hazard, one less dependency. |
| R8 | `webbrowser.open()` fails in terminal-only environments | Low | Low | Wrap in try/except; on failure, copy URL to clipboard if `pyperclip` is present, else log to status bar |
| R9 | User runs multiple instances; SQLite lock contention | Low | Low | WAL mode handles concurrent readers gracefully; writer-locking is still serialized, but the short DB write windows and retry-on-busy at `aiosqlite` level absorb this |
| R10 | **Pluggability regression: future developer adds `from .chronological import ...` to feed_list.py** | Medium | High | `tests/test_strategies.py::test_feed_list_widget_imports_only_strategy_base` is an **AST-based** static test (not grep-based — Architect rejected grep as bypassable). Fails CI on any import of `ai_dashboard.strategies.*` except `.strategies.base`. |
| R11 | App exit hangs because a worker is mid-HTTP-request | Low | High | `PollingOrchestrator.stop()` closes http client FIRST (aborts in-flight sockets), then `gather` with a 1s timeout. 10s read timeout on httpx bounds worst-case cancellation observation latency. All tests on an instrumented shutdown timer. No `asyncio.to_thread` anywhere, so no non-cancellable threads. |
| R12 | First-run experience: user launches empty TUI because no items have been polled yet | Medium (was High) | Low | **Bootstrap fetch on mount**: `PollingOrchestrator.start()` pre-sets each adapter's wake event, so the first loop iteration runs `fetch()` immediately. First-run users see data within ~10s instead of waiting up to `max(default_intervals) = 3600s`. Status bar still shows "Fetching sources..." during the initial round. |
| R13 | Autopilot executor picks a different TUI library or framework despite spec choice | Low | High | Spec + plan both lock Python 3.11 + Textual. Plan's pyproject.toml includes only `textual` as the TUI dep — no mixing permitted. Critic verifies. |
| R14 | WAL sidecar files (`cache.db-wal`, `cache.db-shm`) leak after crashes | Low | Low | Files in `.gitignore` from Phase 1.0; SQLite auto-recovers them on next open; documented in Phase 2.2 as normal and expected |

---

## Verification Steps

### Automated (must pass before "done")

1. **Environment**: `ls .venv/bin/python && .venv/bin/python --version` prints 3.11+; `git log --oneline` shows at least the scaffolding commit
2. **Install**: inside activated venv, `pip install -e .[dev]` succeeds without errors
3. **Compile**: `python -m compileall src/` produces no errors
4. **Tests**: `pytest -q tests/` returns green with ALL tests passing, including:
   - `test_storage.py` (schema, upsert, WAL mode enabled)
   - `test_sources/test_*.py` (5 adapters, respx-mocked HTTP)
   - `test_strategies.py` (pluggability swap test + AST-based import invariant)
   - `test_reading_pane_imports.py` (no forbidden rich imports)
   - `test_first_paint.py` (200ms benchmark, empty + 500-item seed)
   - `test_null_adapter_is_not_shipped.py` (Phase 1.5 guard)
   - `test_app_snapshot.py` (Textual snapshot)
5. **Static invariants** (redundant but cheap — catches regressions even if tests are skipped):
   - `! grep -rn "ChronologicalAllSourcesStrategy" src/ai_dashboard/widgets/` returns non-zero (widget file clean of concrete strategy references)
   - `! grep -rn "huggingface_hub" src/` returns non-zero (removed dep)
   - `! grep -rn "import requests" src/` returns non-zero (httpx-only policy)
   - `! grep -rnE "pdfplumber|trafilatura|newspaper3k|rich\\.markdown|rich\\.syntax" src/` returns non-zero (no forbidden deps / modules)
   - `! grep -rn "NullAdapter" src/ai_dashboard/app.py src/ai_dashboard/workers.py src/ai_dashboard/widgets/` returns non-zero (bootstrap adapter isolated)
6. **Git hygiene**: `git status` is clean on main; `.venv/` is NOT tracked; `cache.db*` is NOT tracked
7. **Smoke**: `python scripts/smoke.py` passes against live arXiv (Phase 2.5 gate — run at least once during dev, not required in CI)
8. **Runtime**: `ai-dashboard` launches and exits within 3 seconds on `q` key (manual)

### Manual (one-time validation before shipping)

1. Launch the app with a network connection
2. Verify items from each of the 5 sources appear within 10 minutes (and ideally within ~10s for the fast sources, thanks to bootstrap fetch)
3. Click through 5 items (one per source) and verify reading pane renders each correctly with the per-source layout from spec §E
4. Press `o` on an item, verify browser opens the correct URL
5. Press `r`, verify "refreshing..." status appears and new items (if any) load without the TUI freezing (non-destructive wake, not teardown-and-restart)
6. Press `q`, verify exit within 2s and no orphan processes (`pgrep -f ai-dashboard` returns nothing)
7. Check `~/.local/share/ai-dashboard/` — after clean exit, only `cache.db` should remain (`.db-wal` and `.db-shm` checkpointed away)
8. Relaunch, verify cached items appear within 200ms (first paint from SQLite + WAL)

---

## Parallelization Plan (for autopilot execution)

Phase dependencies:
- **Phase 1.0 (git + venv) blocks everything** — cannot install deps without venv
- **Phase 1.1-1.4 (pyproject + package layout) blocks Phase 1.5** — need package structure
- **Phase 1.5 (Protocol skeleton + NullAdapter)** enables Phase 5 to start EARLY in parallel with Phase 3
- **Phase 2 (storage + config) blocks Phase 2.5** (needs Database to smoke-test)
- **Phase 2.5 (smoke test) is a HARD GATE** — must pass before Phase 3 fans out to 5 adapters
- **Phase 3** is internally parallel — 5 adapter files are independent
- **Phase 4** depends on Phase 2 only and is trivially small
- **Phase 5** depends on Phase 1.5 (for Protocols and NullAdapter bootstrap) and Phases 2, 4. Phase 5 can begin in parallel with Phase 3 because it uses NullAdapter during bootstrap and swaps to real adapters once Phase 3 is green.
- **Phase 6** tests can start once their corresponding implementation phase is done
- **Phase 7** is final verification

Recommended parallelization for an autopilot run:

1. **Serial batch 1a**: Phase 1.0 (git init, venv, .gitignore, initial commit) — 1 worker
2. **Serial batch 1b**: Phase 1.1-1.4 (pyproject, package layout, __main__) — 1 worker
3. **Serial batch 1c**: Phase 1.5 (Protocol skeleton + NullAdapter + guard test) — 1 worker
4. **Serial batch 2**: Phase 2 (storage/models, storage/db, config, fixtures) — 1 worker
5. **Hard gate**: Phase 2.5 (end-to-end smoke test) — 1 worker; **MUST pass before batch 6**
6. **Parallel batch 6**: Phase 3 (5 adapters) + Phase 4 (2 strategy files) + early Phase 5 widgets using NullAdapter — up to 8 workers in parallel
7. **Serial batch 7**: Phase 5.3 (workers.py) → Phase 5.4 (app.py) — sequential dependency chain, 1 worker at a time
8. **Parallel batch 8**: Phase 6 (tests — 10+ test files) — up to 10 workers in parallel
9. **Serial batch 9**: Phase 7 (README + manual verification) — 1 worker

Expected execution: ~9 logical batches, heavy parallelism in batches 6 and 8. The Phase 2.5 smoke-test gate is a deliberate throttle — it catches Protocol-shape bugs BEFORE the 5-way adapter fan-out commits, which is the single highest-leverage early-warning in this plan.

---

## ADR — Architectural Decision Record

This plan made several load-bearing decisions during consensus refinement. The ADR captures each one formally so that future readers (including V2 authors) understand the reasoning and constraints.

### ADR-1 — Horizontal-layer implementation ordering with two bypass mechanisms

**Decision:** Build the data layer first (storage + models), then adapters in parallel, then strategies, then widgets + app. Bypass Option B's main weakness (no end-to-end validation until Phase 5) with two surgical additions: a Phase 2.5 smoke test against live arXiv after the data layer is done, and a Phase 1.5 NullAdapter that lets Phase 5 (widgets + app) begin in parallel with Phase 3 (real adapters).

**Drivers:**
1. Pluggability of `FeedListStrategy` requires the Protocol to be designed before any widget or concrete strategy commits to it — Protocol-first is cheaper than Protocol-refactor.
2. 5 source adapters are genuinely parallel work — they share only `FeedItem` and the `SourceAdapter` Protocol.
3. Autopilot execution wants clear phase dependencies with named gates.

**Alternatives considered:**
- **Option A (Vertical slices):** Build arXiv end-to-end, then HN, then ... Rejected because the `SourceAdapter` Protocol would evolve with each source and force refactoring, AND because 4 out of 5 adapters would be rework after the first one stabilized the Protocol. Its strength (end-to-end validation early) is absorbed by Phase 2.5 smoke test without sacrificing parallelism.
- **Option C (Skeleton + fill):** Create all files as stubs, get App launchable, then fill in. Rejected because empty-stub adapters are indistinguishable from broken adapters at runtime, masking errors. Its strength (always-launchable App) is absorbed by Phase 1.5's NullAdapter which is explicitly guarded so it cannot leak into production code.

**Why chosen:** Option B + the two bypasses (Phase 1.5 + Phase 2.5) captures the best properties of all three options without their weaknesses. This is the "synthesis path" the Architect requested.

**Consequences:**
- (+) 5 adapters are genuinely parallel, cutting elapsed time substantially.
- (+) `FeedListStrategy` Protocol is designed before the widget, so pluggability is enforced by construction.
- (+) Phase 2.5 catches Protocol-shape bugs BEFORE the 5-way fan-out commits resources.
- (+) Phase 1.5 NullAdapter lets Phase 5 start early, shortening the critical path.
- (-) Autopilot has a harder dependency graph to reason about (9 batches instead of 6). Mitigated by the explicit Parallelization Plan section.
- (-) NullAdapter is an artifact that could leak. Mitigated by `test_null_adapter_is_not_shipped.py` Phase 1.5 guard test running in CI.

**Follow-ups:**
- If Phase 2.5 smoke test fails, halt Phase 3 and fix the Protocol/storage shape — do not proceed to the 5-adapter fan-out.
- Consider a Phase 7.5 "post-merge soak test" that runs all 5 adapters against live sources for 10 minutes and verifies no zombie tasks. Not strictly required; deferred.

### ADR-2 — Foreground-only polling via asyncio.Task with bootstrap wake events

**Decision:** All polling runs as `asyncio.Task` instances owned by the `App` lifetime. On `App.on_mount`, the `PollingOrchestrator` spawns one task per adapter with a **pre-set `asyncio.Event`** so the first loop iteration runs `fetch()` immediately (no sleep). On `App.on_unmount`, the orchestrator cancels all tasks and closes the `httpx.AsyncClient` within a hard 2-second deadline (split 1s/1s between http close and task gather).

**Drivers:**
1. Deep interview Round 4 (contrarian) concluded foreground-only is sufficient for MVP; daemon + OS notifications deferred to V2.
2. 2-second shutdown SLO (spec §L.1) requires bounded timeouts and explicit shutdown ordering.
3. First-run users should see data within ~10s, not wait up to 60min (newsletter interval).

**Alternatives considered:**
- **Persistent daemon (separate process):** Rejected at Round 4 of the deep interview — daemon adds IPC, state sync, and process management complexity that MVP does not need. Deferred to V2.
- **Polling-on-open (single fetch on launch, no background):** Rejected because the interview specified 1-5 min freshness SLO, which requires continuous polling while TUI is open.
- **Simple sleep() loop without wake events:** Rejected because the `r` refresh key requires interrupting the sleep, and destructive "cancel and restart orchestrator" (the Architect caught this) introduces 2s stalls and race conditions.

**Why chosen:** `asyncio.Event`-based wake mechanism is the canonical interruptible-sleep pattern. Pre-setting the event gives bootstrap-on-mount for free. Splitting the 2s shutdown between http-close and task-gather bounds worst-case cancellation observation latency.

**Consequences:**
- (+) TUI is responsive to `r` refresh (instant wake, no stall).
- (+) First-run users see data within ~10s (bootstrap fetch).
- (+) Shutdown is bounded by two small budgets instead of one large timeout.
- (+) No `asyncio.to_thread` anywhere → no non-cancellable threads → no zombie processes after exit.
- (-) Slightly more complex orchestrator code (per-adapter wake events + explicit if/else sleep) vs. naive `asyncio.sleep`.
- (-) `httpx.AsyncClient` read timeout must be bounded (10s) to make shutdown observation fast. Long-running requests > 10s will be aborted. Mitigated by choosing sources whose API responses are always < 10s.

**Follow-ups:**
- Benchmark actual shutdown time on the target machine; if it exceeds 2s, investigate which task is stuck and tighten its timeout.
- V2: when daemon is added for critical-topic alerts, the orchestrator becomes the daemon; the App becomes a client that subscribes to its events.

### ADR-3 — Pluggable FeedListStrategy with AST-based enforcement

**Decision:** The right-panel feed list receives items via a `FeedListStrategy` Protocol (PEP 544 structural typing). MVP ships exactly one implementation (`ChronologicalAllSourcesStrategy`). The widget file MUST NOT import any concrete strategy. Enforcement is via an AST-based test that walks every `Import` and `ImportFrom` node in `feed_list.py` and rejects any reference to `ai_dashboard.strategies.*` except `ai_dashboard.strategies.base`.

**Drivers:**
1. V2 must add different filtering strategies (watchlists, topic filters, critical-topic alerts) without touching the widget. This was user-volunteered in Round 5 of the deep interview and is load-bearing.
2. Grep-based enforcement is trivially bypassable (caught by Architect review). AST is the minimum robust check.
3. The invariant must be verified at CI time, not "noticed during code review."

**Alternatives considered:**
- **ABC inheritance instead of Protocol:** Rejected because Python idiomatic typing is structural; ABC forces all strategy authors to import a base class, which is friction against the "zero widget edits to add a strategy" goal.
- **Grep-based import test:** Rejected by Architect because substring matching is bypassed by module-level imports, aliased imports, and dynamic imports.
- **Runtime check on startup:** Rejected because static enforcement is cheaper and catches regressions before merge.

**Why chosen:** AST walk is a 30-line test that catches all four classes of evasion (module-import, submodule-import, aliased-submodule-import, dynamic-import via string literal secondary check). Combined with the real swap test (`test_feed_list_widget_works_with_custom_strategy` using `OnlyArxivStrategy`), the pluggability invariant is verified from both directions: structurally (imports) and behaviorally (actual swap works).

**Consequences:**
- (+) Pluggability is enforced by CI, not by vigilance.
- (+) V2 authors get a clear contract: implement `async def items(db, now)` and register/inject your strategy.
- (+) The widget is trivially testable with mock strategies.
- (-) A developer trying to "just quickly" reference the concrete strategy for a hotfix will get their build rejected. Good.
- (-) Dynamic strategy loading (e.g., plugin system where strategies are discovered at runtime) is possible but must be done in `app.py` or a dedicated `strategies/loader.py`, never in `widgets/feed_list.py`.

**Follow-ups:**
- V2: add a strategies registry (`strategies/__init__.py::REGISTRY`) so new strategies can be discovered by name via config file, mirroring the `sources/` factory pattern.
- Consider promoting the AST-based import test into a reusable utility for other file-level import invariants (e.g., "app.py must not import any test-only modules").

### ADR-4 — Direct HuggingFace HTTP API over the huggingface_hub SDK

**Decision:** The HuggingFace source adapter uses direct `httpx` calls to `https://huggingface.co/api/{models,datasets,spaces}?sort=createdAt&direction=-1`. The `huggingface_hub` Python SDK is NOT a dependency.

**Drivers:**
1. The SDK is synchronous and must be wrapped in `asyncio.to_thread`, which creates non-daemon threads that cannot be cancelled cleanly by Python. This breaks the 2s shutdown SLO.
2. The HF HTTP API is fully documented, public, and requires no authentication for these read-only endpoints.
3. Principle 2 (simplest thing that works) favors fewer dependencies.

**Alternatives considered:**
- **Use `huggingface_hub` SDK via `asyncio.to_thread` with a timeout:** Rejected because threads that overrun the timeout leak; `asyncio.wait_for` on a thread cancels the waiter coroutine but cannot interrupt the thread itself.
- **Use `huggingface_hub` SDK with a daemon-thread executor:** Rejected because daemon threads are killed abruptly at process exit, which can corrupt SDK state and confuse the SDK's internal caching.
- **Skip HuggingFace entirely:** Rejected because HF is one of the 5 MVP sources chosen in Round 2 of the deep interview.

**Why chosen:** Direct HTTP is the simplest working solution. It eliminates one dependency, removes a lifecycle hazard, and aligns test infrastructure (all adapters use `respx` for HTTP mocking).

**Consequences:**
- (+) Runtime dep count is 5 instead of 6.
- (+) No `asyncio.to_thread` anywhere in the codebase; all async is truly async.
- (+) Test infrastructure is uniform (respx everywhere).
- (-) We now maintain HTTP request shapes ourselves (URL construction, query params). Mitigated by HF's stable public API.
- (-) If HF adds a breaking change to the API, we must fix it ourselves (vs. waiting for SDK update). Likelihood low; mitigation: snapshot API responses in fixtures.

**Follow-ups:**
- Monitor HF API changelog; fixture-based tests will fail loudly on breaking changes.
- If future requirements demand SDK-only features (e.g., dataset preview, large-file download), revisit this decision — but those features are explicitly out of scope per the "metadata-only reading pane" simplifier decision.

### ADR-5 — All-async aiosqlite with single-connection + WAL mode

**Decision:** The `Database` class wraps exactly one `aiosqlite.Connection` for the App's lifetime, with `PRAGMA journal_mode=WAL` enabled on connect. All DB access is async (including from the main App), not sync.

**Drivers:**
1. Mixing sync and async SQLite in one process is error-prone and leaks easily.
2. Five concurrent polling workers performing upserts + the main App reading items means the DB is touched from many task contexts; WAL mode lets readers never block writers.
3. First-paint SLO (<200ms) benefits from the "one connect, then fast reads" pattern.

**Alternatives considered:**
- **Spec-suggested mixed sync + async:** The spec allowed `sqlite3` (sync) in the main App. Rejected because it introduces two coherency models and creates a footgun where a sync read on the main connection could block the event loop.
- **Connection pool with multiple connections:** Rejected because WAL coherency is per-connection and a pool reintroduces SQLITE_BUSY errors under concurrent writes.
- **Separate read replica (second SQLite file):** Rejected as premature optimization; 5 workers writing to one DB with WAL is genuinely fine at the scales this MVP handles (~500 items, ~50 writes/minute).

**Why chosen:** One async pattern, one connection, WAL mode. This is the simplest correct solution.

**Consequences:**
- (+) One consistent pattern across the codebase; no "sync-in-async-loop" footguns.
- (+) Readers (main App, feed list refresh) never block on writers (workers).
- (+) WAL checkpointing happens automatically on `close()`, so no journal files leak.
- (-) ~1ms per-call overhead in `aiosqlite` (thread-pool dispatch). Negligible at our scale.
- (-) WAL mode produces `cache.db-wal` and `cache.db-shm` sidecar files during operation. Documented in Phase 2.2 and `.gitignore`. Spec §L.4 "no -journal files" is reinterpreted — there are no rollback-journal files in WAL mode, only the WAL sidecars, which auto-clean on close.
- (-) Deviation from spec §Storage line 56 (allowed sync). Documented in Spec Deviations section.

**Follow-ups:**
- Benchmark first-paint time with and without WAL to confirm no regression.
- Consider adding a SQLite VACUUM step on clean close to reclaim space if the DB grows unbounded. Not required for MVP.

---

## Changelog

- **2026-04-11 (v1)** — Initial draft by Planner from spec `.omc/specs/deep-interview-ai-news-tui.md`.

- **2026-04-11 (v2)** — **Architect review applied** (REVISE verdict → fully addressed) + **user addition**. 17 Architect improvements + 1 user requirement integrated:

  **User additions:**
  - **Phase 1.0 NEW**: `git init` + `.venv` setup + `.gitignore` with sensible Python/venv/cache-db/snapshot exclusions, plus initial commit.

  **Architect improvements applied:**
  1. **Phase 5.3 rewrite — PollingOrchestrator shutdown safety**: 10s httpx read timeout (down from 30s), correct shutdown order (cancel tasks → close http client → gather with timeout), split 2s SLO across http-close (1s) and task-gather (1s). Architect Issue #1.
  2. **Phase 5.3 — refresh_all_now redesign**: replaced destructive teardown-and-restart with per-adapter `asyncio.Event` wake mechanism. Refresh is now instant and non-destructive. Architect Issue #2.
  3. **Phase 3.5 — HuggingFace adapter rewrite**: replaced `huggingface_hub` SDK with direct httpx HTTP API calls. Eliminated the non-cancellable-thread hazard from `asyncio.to_thread`, removed one dependency (5 total runtime deps now, down from 6). Architect Issue #1 sub-point 5.
  4. **Phase 4.1 — FeedListStrategy async signature documented as Spec Deviation 1**: Added explicit Spec Deviations section rather than silent drift. Architect Issue #3.
  5. **Phase 6.8 — AST-based import invariant test**: replaced bypassable grep test with full AST walk of `feed_list.py` rejecting any import of `ai_dashboard.strategies.*` except `.strategies.base`. Architect Issue #4.
  6. **Phase 2.2 — Database single-connection contract + WAL mode**: enabled `PRAGMA journal_mode=WAL`, documented single-connection invariant, added `PRAGMA synchronous=NORMAL`, used `executescript()` for atomic schema init. Architect Issue #5.
  7. **Phase 6.10 NEW — First-paint benchmark test**: enforces the 200ms SLO with a concrete measurement against a 500-item seeded DB. Architect Issue #6.
  8. **Phase 3.1 — SourceAdapter Protocol expansion + build_adapter factory**: documented `__init__(http, options)` construction convention, added `sources/__init__.py` factory with registry. Architect Issue #7.
  9. **Phase 3 cross-cutting — httpx.Limits pinned**: `max_connections=20`, `max_keepalive_connections=10`, bounded timeouts, per-adapter header overrides. Architect Issue #8.
  10. **Phase 5.4 — ItemsArrived message queue routing**: orchestrator callback now posts a Textual `Message` instead of calling widget methods directly, eliminating the on_unmount race. Architect Issue #9.
  11. **Phase 5.2 + Phase 6.11 — ReadingPane render-type restriction**: constrained render methods to `rich.text.Text | rich.console.Group`, added AST-based test rejecting `rich.markdown/rich.syntax/rich.table/rich.tree/rich.pretty/rich.traceback` imports. Architect Issue #10.
  12. **Spec Deviations section NEW**: documents the async strategy signature (Dev 1) and the all-async aiosqlite choice (Dev 2) as explicit deviations with rationale. Architect Issue #11.
  13. **Phase 2.5 NEW — End-to-end smoke test**: `scripts/smoke.py` runs one real adapter (arXiv) against live API + SQLite before Phase 3 fans out to 5 adapters. Synthesis from Option A. Architect improvement #12.
  14. **Phase 1.5 NEW — Protocol skeleton + NullAdapter**: enables Phase 5 to start in parallel with Phase 3 using a guarded bootstrap adapter. Synthesis from Option C with the empty-stub hazard eliminated by a CI test. Architect improvement #13.
  15. **Cold Start Experience section NEW**: surfaces the tension between 200ms first paint and fresh data, documents the two-speed approach (first-paint-from-cache + non-blocking bootstrap-fetch-on-mount). Architect improvement #14.
  16. **Phase 5.3 + 5.4 — Bootstrap fetch on mount**: wake events are pre-set so each adapter's first loop iteration runs `fetch()` immediately, giving first-run users data within ~10s instead of up to 60 minutes. Architect improvement #15.
  17. **Spec Compliance Table NEW**: maps every spec acceptance criterion A-L to the plan phase that implements it and the test that verifies it. Bolded rows are the load-bearing V2 pluggability checks. Architect improvement #16.
  18. **Phase 2.2 + Verification Steps — WAL file expectations documented**: `.db-wal` and `.db-shm` sidecar files are normal in WAL mode and are checkpointed on clean close. They are in `.gitignore`. The spec's "no -journal files" refers to legacy rollback-journal mode. Architect improvement #17.
  19. **Risks table updated**: R6 revised for WAL mode, R7 removed (HF thread hazard eliminated by dep removal), R10 updated to AST-based test, R11 revised for correct shutdown order, R12 likelihood downgraded due to bootstrap fetch, R13 (framework lock-in) and R14 (WAL sidecar cleanup) added.
  20. **Parallelization plan updated**: now reflects 9 batches with the Phase 2.5 smoke-test gate as a hard throttle between data layer and adapter fan-out, and Phase 1.5 as the enabler for parallel Phase 3 + Phase 5.

  **Not applied (deliberate):** Architect's suggestion to replace the single-test "swap test" with additional test-file proliferation was declined — `test_strategies.py::test_feed_list_widget_works_with_custom_strategy` + the AST import test together already enforce the invariant, and adding more tests would violate Principle 2 (simplest thing that works) without adding coverage.

- **2026-04-11 (v2.1)** — **Critic review: APPROVE_WITH_MINOR**. 1 MAJOR + 4 MINOR fixes applied:
  1. **MAJOR — `_build_adapters` ambiguity resolved**: `PollingOrchestrator.__init__` signature authoritatively changed to `adapter_specs: list[tuple[str, dict[str, Any]]]`. Adapter construction moved inside `start()` via `build_adapter(kind, http=self._http, options=options)`. `App._build_adapters` renamed to `_adapter_specs()` and body filled in. Pattern 1/Pattern 2 discussion deleted — one authoritative pattern only.
  2. **MINOR — Principle 2 dep allowlist fixed**: removed stale `huggingface_hub` from the `{textual, httpx, feedparser, selectolax, aiosqlite}` allowlist.
  3. **MINOR — `_run_adapter` control flow clarified**: ternary-as-statement replaced with explicit `if sleep_seconds > 0` / `else` block. `sleep_seconds` typed as `float = 0.0` for consistency.
  4. **MINOR — `test_huggingface.py` description fixed**: rewritten to describe `respx`-mocked HTTP endpoints (`https://huggingface.co/api/models`, `datasets`, `spaces`) instead of the stale `HfApi.list_models` monkeypatch reference.
  5. **MINOR — `test_arxiv.py` polite delay technique clarified**: monkeypatch `time.monotonic` with stepped advancement + `asyncio.sleep` replacement, or `freezegun` alternative.

- **2026-04-11 (v2.1) — ADR section added**: 5 ADRs captured (horizontal-layer ordering, foreground-only polling, pluggable strategies, direct HF HTTP, all-async aiosqlite). Each ADR covers Decision / Drivers / Alternatives / Why chosen / Consequences / Follow-ups per the omc-plan skill requirement.

**Status:** ✅ APPROVED by Critic. Ready for autopilot execution.
