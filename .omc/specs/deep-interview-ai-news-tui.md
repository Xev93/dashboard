# Deep Interview Spec: AI News Terminal Dashboard

## Metadata
- **Interview ID:** di-ai-terminal-dashboard-2026-04-11
- **Rounds:** 7
- **Final Ambiguity Score:** 10.1%
- **Type:** greenfield
- **Generated:** 2026-04-11 (Asia/Kuala_Lumpur)
- **Threshold:** 20%
- **Status:** PASSED
- **Challenge modes used:** Contrarian (R4), Simplifier (R6)

## Clarity Breakdown (Final — Round 7)

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.92 | 0.40 | 0.368 |
| Constraint Clarity | 0.92 | 0.30 | 0.276 |
| Success Criteria Clarity | 0.85 | 0.30 | 0.255 |
| **Total Clarity** | | | **0.899** |
| **Ambiguity** | | | **10.1%** |

## Goal

Build a **Python + Textual** terminal user interface (TUI) application that displays a near-realtime "delta feed" of new cutting-edge AI developments from five specific upstream sources. The primary user action is opening the TUI to answer the question: *"what's new in AI since I last checked?"*

The TUI is a single-process, foreground-only application. When launched, it opens a two-panel layout showing items from all five sources merged by publish time on the right panel, and a reading pane on the left that updates when the user navigates the right panel. Background asyncio workers poll the sources on per-source cadences (1-5 minutes for fast sources, up to 60 minutes for slow ones) while the TUI is open; when the user quits, all workers terminate cleanly. There is no background daemon, no OS push notifications, and no extra content fetching beyond what the source APIs return in their initial payloads.

The feed-list panel receives its items via a **pluggable filter strategy interface** so that V2 can introduce alternative views (topic filters, watchlists, critical-topic alerts) without modifying the panel code.

## Constraints

### Runtime & Language
- **Python 3.11+** (required for modern async, `match` statements, `tomllib`)
- **Textual** — latest stable release — is the TUI framework; no mixing with other TUI libs
- Project managed via `pyproject.toml`; dependency install with `uv` or `pip`
- Entry point is a console script (e.g., `ai-dashboard`) that launches a `textual.app.App` subclass

### HTTP & Async
- **All HTTP is async via `httpx.AsyncClient`** — no `requests`, no blocking calls on the main loop
- All polling runs as `asyncio.Task` instances owned by the App; cancelled on App unmount
- Each source has its own `asyncio.Semaphore` or rate limiter honoring that source's API terms
- Global HTTP timeout: 30s per request; 3 retries with exponential backoff on 5xx / network errors

### Source Matrix (MVP v1 — all required)

| Source | Endpoint | Access Method | Default fetch_interval | Notes |
|---|---|---|---|---|
| arXiv (cs.LG, cs.CL, cs.AI, cs.CV) | `http://export.arxiv.org/api/query` | Atom feed via httpx | 600s (10min) | Polite — arXiv asks 3s between queries minimum |
| HackerNews (AI-filtered) | `https://hacker-news.firebaseio.com/v0/` | Firebase REST | 120s (2min) | Fetch new stories; filter by keyword match against `["AI","ML","LLM","GPT","Claude","OpenAI","Anthropic","neural","model","transformer","diffusion","agent","LoRA"]` in title + URL |
| GitHub Trending (ML) | `https://github.com/trending/python?since=daily`, `trending?spoken_language_code=en` | HTML scrape via `selectolax` | 1800s (30min) | Trending has no API. Respect robots.txt. Filter to AI-adjacent repos by topic/language/keyword |
| HuggingFace | `huggingface_hub.list_models()` + `list_datasets()` + `list_spaces()` | Official `huggingface_hub` package | 600s (10min) | New/updated models in last N hours; ranked by `createdAt` desc |
| AI Newsletters | RSS via `feedparser` | HTTP RSS | 3600s (60min) | Default RSS set: Import AI (jack-clark.net), The Batch (deeplearning.ai), TLDR AI (tldr.tech/ai). Configurable via a TOML/YAML `sources.toml` file |

### Storage
- **SQLite** via stdlib `sqlite3` (async via `aiosqlite` acceptable for fetchers; main App can use sync with care)
- DB file: `~/.local/share/ai-dashboard/cache.db` (respect XDG_DATA_HOME)
- Schema version column; migration function runs on App startup

### Layout (load-bearing)
- **Reading pane on the LEFT (primary, ~65-75% width)**, feed list on the RIGHT (~25-35% width)
- Note: this is the **reverse** of the conventional "list-left, detail-right" pattern (Outlook / mutt). Confirmed by user in Round 5. Keybindings reflect this — navigation keys move the selection in the **right** panel.
- Textual CSS: horizontal container → (`#reading` 2fr / `#feed-list` 1fr)

### Lifecycle
- Workers spawned on `App.on_mount`, cancelled on `App.on_unmount` with 2s timeout
- No daemon, no systemd unit, no `launchctl` plist, no pid files
- Clean exit on Ctrl+C and `q` key

### V2 Pluggability (hard architectural requirement)
- The right-panel feed list receives items via a `FeedListStrategy` **Protocol** (PEP 544)
  ```python
  class FeedListStrategy(Protocol):
      name: str
      def items(self, db: Database, now: datetime) -> Iterable[FeedItem]: ...
  ```
- MVP ships **one** implementation: `ChronologicalAllSourcesStrategy`
- The strategy is injected into the feed-list widget at construction — no global state, no registry scanning
- Adding a new strategy in V2 MUST require zero edits to the feed-list widget file

### Reading Pane Rendering (no extra fetching)
- Plain text rendering only (Textual's `Static` or `RichLog` widgets)
- Source payloads are already sufficient — use ONLY fields present in the initial API response
- No PDF parsing, no README fetching, no markdown rendering, no image rendering
- Press `o` to open the primary URL in system browser via `webbrowser.open()`

## Non-Goals (explicitly OUT of MVP)

| Non-goal | Reasoning |
|---|---|
| Background daemon while TUI is closed | Confirmed in Round 4 contrarian round — foreground-only is sufficient; daemon deferred to V2 |
| OS push notifications (macOS Notification Center, etc.) | Deferred to V2 along with daemon |
| Reddit, Twitter/X, lab company blogs as sources | User explicitly did not select these in Round 2 |
| Watchlists / critical topic tracking | Deferred to V2 (the pluggable FeedListStrategy is the foundation for this) |
| Full PDF / HTML / README content extraction | Cut in Round 6 simplifier round to avoid pdfplumber/newspaper3k/readability dependencies |
| Markdown rendering in reading pane | Cut with content extraction — plain text only |
| Terminal image rendering (sixel / kitty graphics) | Cut with rich rendering |
| Multi-user, auth, networked storage | Single-user local-only |
| Search / filter UI (beyond the default strategy) | All filtering is done at the strategy layer; no interactive filter UI in MVP |
| Bookmarking, note-taking, tagging on items | Deferred |
| ML-based ranking / personalization of items | Deferred |
| Mobile or web UI | Terminal-only; user's core requirement |

## Acceptance Criteria

### A. Project Structure & Tech Stack
- [ ] `pyproject.toml` declares Python 3.11+ and dependencies: `textual`, `httpx`, `feedparser`, `huggingface_hub`, `selectolax`, (optional `aiosqlite`, `pytest`, `pytest-asyncio`)
- [ ] Entry point: console script `ai-dashboard` launches `textual.app.App` subclass
- [ ] No blocking I/O on main event loop (verified by `asyncio.get_event_loop().slow_callback_duration`)
- [ ] Project layout: `src/ai_dashboard/{app.py, sources/, storage/, strategies/, widgets/}`

### B. Source Adapters
- [ ] Each of the 5 sources has an adapter class implementing `SourceAdapter` Protocol with `async def fetch() -> list[FeedItem]`
- [ ] Adapters are pure functions of HTTP responses → `FeedItem` list; no storage side-effects
- [ ] Each adapter handles its own error/retry/rate-limit locally; failures are logged and do not crash the app
- [ ] arXiv adapter honors 3-second minimum inter-request delay
- [ ] GitHub Trending adapter uses `selectolax` for HTML parsing; uses a polite User-Agent header
- [ ] HN adapter filters by configurable AI keyword list matched against title + URL (case-insensitive, word-boundary)
- [ ] HuggingFace adapter uses `huggingface_hub.list_models`/`list_datasets`/`list_spaces` with `sort="createdAt"` descending
- [ ] Newsletter adapter uses `feedparser` on each configured RSS URL

### C. Polling & Background Workers
- [ ] Each source has its own `asyncio.Task` spawned on `App.on_mount`
- [ ] Default intervals: arXiv 600s, HN 120s, GitHub Trending 1800s, HuggingFace 600s, Newsletters 3600s
- [ ] Intervals are overridable via `sources.toml` config file in `~/.config/ai-dashboard/`
- [ ] On fetch completion, new items are upserted into SQLite and the feed-list widget is notified via Textual's reactive system / messages
- [ ] On fetch failure, the source's `consecutive_failures` counter increments; after 5 consecutive failures, back off to 2x the configured interval until success
- [ ] On `App.on_unmount`, all tasks are cancelled with a 2s timeout; app exits cleanly

### D. Layout & Display (Textual)
- [ ] Root layout: horizontal `Container` with `#reading-pane` (2fr) and `#feed-list` (1fr)
- [ ] `#feed-list` is a `DataTable` or `ListView` with columns: [source_tag, title_truncated, relative_time]
- [ ] Items sorted descending by `published_at`
- [ ] Navigation: `j`/`k` and ↓/↑ move selection in `#feed-list`
- [ ] Selecting an item updates `#reading-pane` within 100ms
- [ ] Relative time rendering: "now", "3m", "1h", "6h", "2d" — computed from `published_at`

### E. Reading Pane Per-Source Layout
- [ ] **arXiv paper:** title / authors / primary category / abstract / arxiv_id / published_date
- [ ] **HN story:** title / points / comments / submitted_by / submitted_at / text (if present) / url
- [ ] **GitHub Trending:** name / owner / stars / language / description / url
- [ ] **HuggingFace:** id / pipeline_tag / author / downloads / last_modified / short card summary
- [ ] **Newsletter:** title / publication / pub_date / summary / url
- [ ] All rendered as plain text with simple styling (colors, separators — no markdown)

### F. Keybindings
- [ ] `q` — quit (clean exit within 2s)
- [ ] `r` — force refresh all sources immediately
- [ ] `o` — open the selected item's URL in the system browser via `webbrowser.open()`
- [ ] `<space>` — mark selected item as read (toggles `seen` flag)
- [ ] `j`/`k`/↓/↑ — navigate feed list
- [ ] `?` — show help overlay listing keybindings

### G. Delta / Unread Semantics
- [ ] On launch, items are loaded from the SQLite cache first — first paint within 200ms
- [ ] `user_state.last_check_time` is persisted on every exit
- [ ] Items with `published_at > last_check_time` are visually marked (bold, or a `*` prefix, or a color accent) in the feed list
- [ ] Pressing `<space>` flips the `seen` flag and updates visual marking

### H. Freshness SLO (test against mocks)
- [ ] Given a mock source returning a new item at T=0, the item appears in the feed list by T = `fetch_interval_seconds + 10s`
- [ ] Refresh-all key `r` triggers immediate fetch of every source; new items visible within 10s in test environment

### I. Storage Schema
- [ ] SQLite schema version 1:
  ```sql
  CREATE TABLE feed_items (
    id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL,  -- 'arxiv' | 'hn' | 'github_trending' | 'huggingface' | 'newsletter'
    source_uid  TEXT NOT NULL,  -- source-specific unique id
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    published_at TEXT NOT NULL, -- ISO8601
    raw_payload TEXT NOT NULL,  -- JSON
    seen        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE(source_kind, source_uid)
  );
  CREATE TABLE sources (
    kind                  TEXT PRIMARY KEY,
    last_fetched          TEXT,
    next_fetch            TEXT,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE user_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
  ```
- [ ] `UNIQUE(source_kind, source_uid)` ensures idempotent re-fetching (dedup)
- [ ] Schema migration: at startup, compare `schema_version.version` to current; if mismatch, migrate or drop-and-recreate (MVP: drop-and-recreate is acceptable)

### J. V2 Pluggability Verification
- [ ] `FeedListStrategy` Protocol exists in `src/ai_dashboard/strategies/base.py`
- [ ] `ChronologicalAllSourcesStrategy` implements it in `strategies/chronological.py`
- [ ] The feed-list widget takes a `FeedListStrategy` instance as a constructor argument
- [ ] There is NO reference to `ChronologicalAllSourcesStrategy` inside the feed-list widget file
- [ ] A second toy strategy (`OnlyArxivStrategy`, used only in tests) can be swapped in with zero edits to the widget file — **this is the acceptance test**

### K. Testing
- [ ] pytest + pytest-asyncio configured
- [ ] Unit test per `SourceAdapter` using recorded API responses (fixture JSON/XML files in `tests/fixtures/`)
- [ ] Integration test for end-to-end polling with mocked `httpx`
- [ ] Textual snapshot test (`pytest-textual-snapshot`) for main app layout
- [ ] Pluggability test: instantiate app with `OnlyArxivStrategy`, assert only arXiv items appear

### L. Lifecycle Correctness
- [ ] Pressing `q` exits within 2 seconds (no hanging tasks)
- [ ] `Ctrl+C` exits cleanly
- [ ] After exit, `ps` shows no orphan Python processes
- [ ] After exit, SQLite WAL is committed, no `-journal` files left behind

## Assumptions Exposed & Resolved

| # | Assumption | How it was challenged | Resolution |
|---|---|---|---|
| 1 | "Tracking AI developments" = browsing news | R1 — asked for the ONE thing user most wants to see in 5 seconds | Resolved as *delta feed* ("what's new since I last checked") — not dashboard/alerts/benchmarks |
| 2 | All sources are equally important | R2 — forced explicit MVP vs nice-to-have choice | 5 sources locked: arXiv, HN filtered, GitHub Trending, HF, newsletters. Reddit, Twitter, lab blogs cut. |
| 3 | "Realtime" means push/subscribe | R3 — asked for concrete freshness SLO with specific timestamp example | Resolved as 1-5 min polling — not sub-second push |
| 4 | Polling requires a persistent daemon (Contrarian challenge) | R4 — challenged whether freshness matters while TUI is closed | Daemon **cut from MVP**. Foreground-only with asyncio workers. V2 adds daemon + notifications if/when watchlists are added. |
| 5 | Layout is list-left / detail-right (conventional) | R5 — presented 5 layout options | Resolved as reversed orientation: **reading pane left, feed list right** |
| 6 | Reading pane needs rich rendering (Simplifier challenge) | R6 — asked for minimum viable reading experience | Resolved as **metadata + excerpt from initial payload**. No PDF parsing, no markdown, no images, no content fetching. Massive dependency cut. |
| 7 | Tech stack would be inferred from context | R7 — direct question with trade-offs per option | Resolved as **Python 3.11 + Textual + httpx + feedparser + huggingface_hub + selectolax + SQLite** |
| 8 | Filtering is a one-off implementation | R5 — user spontaneously flagged V2 pluggability requirement | Locked as **`FeedListStrategy` Protocol** with one default implementation; verified by the "swap test" in acceptance criteria |

## Technical Context (Greenfield)

- Working directory `/Users/dev/projects/dashboard` is empty — true greenfield
- No existing code, no dependencies, no git history
- No constraints inherited from prior choices
- Target platform: macOS (primary per user environment `darwin`). Should also work on Linux without modification. Windows best-effort (Textual supports Windows but arXiv/GitHub Trending scraping behavior is identical).
- User has Python development environment (per session context) — Python + Textual is minimal friction

### Recommended Project Layout
```
dashboard/
├── pyproject.toml
├── README.md
├── src/
│   └── ai_dashboard/
│       ├── __init__.py
│       ├── __main__.py         # python -m ai_dashboard entry
│       ├── app.py              # Textual App subclass
│       ├── config.py           # sources.toml loader
│       ├── sources/
│       │   ├── base.py         # SourceAdapter Protocol
│       │   ├── arxiv.py
│       │   ├── hackernews.py
│       │   ├── github_trending.py
│       │   ├── huggingface.py
│       │   └── newsletter.py
│       ├── storage/
│       │   ├── db.py           # SQLite init, migrations
│       │   └── models.py       # FeedItem dataclass, DB row <-> model
│       ├── strategies/
│       │   ├── base.py         # FeedListStrategy Protocol
│       │   └── chronological.py
│       ├── widgets/
│       │   ├── feed_list.py    # right panel
│       │   └── reading_pane.py # left panel
│       └── workers.py          # asyncio Task orchestration
├── tests/
│   ├── fixtures/
│   │   ├── arxiv_response.xml
│   │   ├── hn_topstories.json
│   │   ├── github_trending.html
│   │   ├── hf_models.json
│   │   └── newsletter.xml
│   ├── test_sources/
│   ├── test_strategies.py      # pluggability swap test
│   └── test_app_snapshot.py
└── .omc/
    └── specs/
        └── deep-interview-ai-news-tui.md   # this file
```

## Ontology (Final — Round 7)

| Entity | Type | Fields | Relationships |
|---|---|---|---|
| `FeedItem` | core domain | id, source_kind, source_uid, title, url, published_at, raw_payload, seen, created_at | belongs_to Source; rendered by ReadingPane and listed by FeedList |
| `Source` | core domain | kind, endpoint, filter_config, fetch_interval, last_fetched, next_fetch, consecutive_failures | has_many FeedItems |
| `User` | core domain | last_check_time | single-user local-only |
| `Dashboard` | core domain (UI root) | layout_config | contains ReadingPane + FeedList |
| `ReadingPane` | supporting (UI widget) | selected_item_id, renderer_strategy | displays one FeedItem at a time |
| `FeedList` | supporting (UI widget) | strategy, visible_items, selection_index | produces selection events consumed by ReadingPane |
| `FeedListStrategy` | core abstraction (V2 seam) | name, items() method | strategy pattern — pluggable |
| `Paper` | supporting (source polymorph) | authors, abstract, arxiv_id, primary_category | is_a FeedItem for arXiv |
| `Repo` | supporting (source polymorph) | owner, stars, language, description | is_a FeedItem for GitHub Trending |
| `HNStory` | supporting (source polymorph) | points, comment_count, submitted_by, text | is_a FeedItem for HN |
| `NewsletterItem` | supporting (source polymorph) | publication, summary, pub_date | is_a FeedItem for Newsletters |
| `HFResource` | supporting (source polymorph) | hf_kind (model/dataset/space), author, downloads, pipeline_tag | is_a FeedItem for HuggingFace |

## Ontology Convergence

| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|---|---|---|---|---|---|
| 1 | 3 | 3 | – | – | N/A |
| 2 | 9 | 6 | 1 (`AIDevelopment` → `FeedItem`) | 2 | 33% |
| 3 | 9 | 0 | 0 | 9 | **100%** (converged) |
| 4 | 9 | 0 | 0 | 9 | 100% |
| 5 | 12 | 3 (`ReadingPane`, `FeedList`, `FeedListStrategy`) | 0 | 9 | 75% |
| 6 | 12 | 0 | 0 | 12 | 100% |
| 7 | 12 | 0 | 0 | 12 | **100%** (final) |

The domain model converged at Round 3 and only expanded at Round 5 when the UI layout introduced widget entities. After Round 5, the model has been stable for three consecutive rounds — **strong evidence of a well-understood domain**.

## Interview Transcript

<details>
<summary>Full Q&A (7 rounds)</summary>

### Round 1 | Targeting: Goal Clarity
**Q:** When you open this dashboard in the morning, what's the ONE thing you most want it to show you within the first 5 seconds?

**A:** What's new since I last checked.

**Ambiguity:** 75.5% (Goal: 0.45, Constraints: 0.10, Criteria: 0.15)

---

### Round 2 | Targeting: Constraints
**Q:** Which source buckets MUST be in the MVP? Pick what you'd actually miss if it wasn't there tomorrow morning.

**A:** arXiv (AI/ML categories), GitHub Trending, HackerNews (filtered), AI newsletters/Substacks, HuggingFace. Notably skipped: Reddit, Twitter/X, lab blogs.

**Ambiguity:** 61.0% (Goal: 0.60, Constraints: 0.35, Criteria: 0.15)

---

### Round 3 | Targeting: Criteria (via freshness constraint)
**Q:** When you said "realtime" — what's the actual freshness you need? If a new arXiv paper is submitted at 10:03am, when do you NEED to see it?

**A:** Within 1-5 minutes (near-realtime polling).

**Ambiguity:** 45.5% (Goal: 0.65, Constraints: 0.55, Criteria: 0.40)

---

### Round 4 | CONTRARIAN MODE | Targeting: Constraints (daemon lifetime)
**Q:** You said you need 1-5 min freshness. But freshness only matters while you're looking. Is "always running" load-bearing or habit?

**A:** For MVP foreground-only is fine. V2 will add critical topic tracking with OS-level push notifications, but that's a separate concern.

**Ambiguity:** 35.5% (Goal: 0.75, Constraints: 0.65, Criteria: 0.50)

---

### Round 5 | Targeting: Criteria (via layout)
**Q:** When the TUI is open, what's the layout? Unified feed, multi-panel, tabbed, grouped, or master-detail?

**A:** Multi-panel: primary/larger pane for reading the selected entry, smaller right-side pane listing entries from every source chronologically. **MVP scope — V2 should have a different filtering mechanism for the right-panel, so it should be built to be interchangeable.**

**Ambiguity:** 24.0% (Goal: 0.85, Constraints: 0.75, Criteria: 0.65)

---

### Round 6 | SIMPLIFIER MODE | Targeting: Criteria (reading pane content)
**Q:** What's the MINIMUM reading pane you'd actually use daily — the point below which you'd stop using the tool?

**A:** Metadata + short summary/abstract already in the initial feed payload.

**Ambiguity:** 16.0% (Goal: 0.90, Constraints: 0.80, Criteria: 0.80) — **below threshold**

---

### Round 7 | Targeting: Constraints (tech stack)
**Q:** Language + TUI framework?

**A:** Python + Textual (recommended for this workload).

**Ambiguity:** 10.1% (Goal: 0.92, Constraints: 0.92, Criteria: 0.85)

</details>

---

**Spec status: PASSED (10.1% ambiguity, below 20% threshold)**

Ready for execution bridge: `omc-plan --consensus --direct` → `autopilot`.
