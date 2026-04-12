# Deep Interview Spec: AI Dashboard V2

## Metadata
- Interview ID: di-ai-dashboard-v2-2026-04-12
- Rounds: 9
- Final Ambiguity Score: 15.0%
- Type: brownfield (V1 at /Users/dev/projects/dashboard)
- Generated: 2026-04-12
- Threshold: 20%
- Status: PASSED
- Challenge modes used: Contrarian (R4), Simplifier (R6)

## Clarity Breakdown

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.95 | 0.35 | 0.333 |
| Constraint Clarity | 0.80 | 0.25 | 0.200 |
| Success Criteria | 0.85 | 0.25 | 0.213 |
| Context Clarity | 0.70 | 0.15 | 0.105 |
| **Total Clarity** | | | **0.850** |
| **Ambiguity** | | | **15.0%** |

## Goal

Upgrade the V1 ai-dashboard from a foreground-only TUI feed reader into a **continuously-collecting, heuristically-ranked, multi-source intelligence dashboard** with interactive search and source-specific views. The daemon polls 24/7 to ensure no items are missed between TUI sessions. New 1st-party and community sources expand coverage. A heuristic ranking strategy surfaces the most relevant items. Source tabs and text filtering make the growing feed navigable.

## V2 Scope (5 items)

1. **Persistent daemon** — continuous 24/7 data collection ensuring historical completeness
2. **New sources** — lab blogs (RSS) + Reddit + research-identified additional sources; 1st-party sources weighted higher
3. **Search/filter UI** — source tabs (All | AX | HN | GH | HF | NL | ...) + `/` text filter bar
4. **New FeedListStrategy implementations** — by-source views via tabs, heuristic-ranked view
5. **Heuristic ranking** — engagement + source authority + keyword boost + recency decay + skip penalty; configurable via config.toml

## Constraints

### Daemon Architecture
- **Dual mode**: CLI-managed (`ai-dashboard daemon start/stop/status`) for dev + launchd plist for production
- `ai-dashboard daemon install` generates `~/Library/LaunchAgents/com.ai-dashboard.daemon.plist` with `KeepAlive=true`
- `ai-dashboard daemon uninstall` removes the plist
- Daemon is the V1 `PollingOrchestrator` extracted to a standalone process writing to the same SQLite DB (WAL mode handles concurrent access)
- TUI becomes a read-mostly client; daemon owns all polling
- PID file at `~/.local/share/ai-dashboard/daemon.pid`
- Daemon logs to `~/.local/share/ai-dashboard/daemon.log`
- On crash, launchd restarts automatically; CLI mode does not auto-restart
- TUI detects whether daemon is running on startup; if yes, disables its own polling (avoids duplicate fetches); if no, falls back to V1 foreground polling

### Source Taxonomy
- **1st-party sources** (arXiv, lab blogs): authoritative, weighted +0.3 in heuristic ranking
- **Community sources** (HN, Reddit, GitHub Trending, HuggingFace): sentiment + trending signal, weighted +0.0
- **Pre-implementation research phase**: before coding new adapters, execute a research task to identify the most useful AI data sources beyond the V1 set + obvious additions. Research output informs which adapters to build.

### New Sources (confirmed)
- **Lab blogs**: OpenAI, Anthropic, DeepMind, Google AI, Meta AI — RSS feeds via the existing newsletter adapter pattern. Classified as 1st-party.
- **Reddit**: r/MachineLearning, r/LocalLLaMA, r/singularity — free JSON API (append `.json` to subreddit URL). Classified as community.
- **Additional sources from research**: TBD by research phase. Candidates include Bluesky (free AT Protocol API), Mastodon AI instances, Semantic Scholar API, Papers With Code, AI conference proceedings feeds.
- **Twitter/X**: NOT committed. Deferred to research phase evaluation. $100+/mo API cost is a concern for a personal tool.

### Search/Filter UI
- **Source tabs**: horizontal tab bar above the feed list with tabs for each source (All | AX | HN | GH | HF | NL | Reddit | Labs | ...)
- Tab selection filters the feed list to that source only; "All" shows everything
- Tabs are navigable via number keys (1=All, 2=AX, 3=HN, ...) or mouse/click
- **Text filter**: press `/` to open a filter bar at the bottom of the feed list
- Type to filter the current tab's items by text match (case-insensitive substring against title + description)
- Press Escape to clear the filter and close the filter bar
- Filter is a UI-level operation on the strategy's output — implemented as a `FilteredStrategy` decorator wrapping the active strategy

### FeedListStrategy Implementations (V2 ships these)
- `ChronologicalAllSourcesStrategy` (existing V1 default)
- `BySourceStrategy(source_kind)` — per-source view used by source tabs
- `HeuristicRankingStrategy` — engagement-ranked view, configurable
- `FilteredStrategy(base, text_filter)` — decorator that filters any base strategy by text match
- Strategy switching via source tabs or a keybinding (e.g., `s` to cycle ranked/chronological)

### Heuristic Ranking Formula
```
score = engagement_normalized     # 0-1 scale (HN points/max_points, GH stars/max_stars, etc.)
      + source_weight             # 1st-party: +0.3, community: +0.0 (configurable)
      + keyword_boost             # +0.2 per match with user's top N search terms (configurable)
      + recency_decay             # e^(-hours_old / 24) — items older than 48h are heavily penalized
      - skip_penalty              # -0.1 per time source_kind was skipped in last 50 views (configurable)
```
- Weights are configurable via `config.toml` under `[ranking]` section
- `engagement_normalized` is per-source: `min(value / percentile_95, 1.0)` to avoid outliers dominating
- Requires new storage: `user_search_history(term, count, last_used)`, `item_view_log(source_kind, source_uid, action, timestamp)` where action ∈ {viewed, skipped}

### Existing V1 Architecture (preserved)
- Python 3.11+ / Textual / httpx / feedparser / selectolax / aiosqlite / trafilatura
- SQLite with WAL mode, single-connection per process (daemon has its own connection, TUI has its own)
- `FeedListStrategy` Protocol — V2 adds new implementations, does NOT change the Protocol
- `SourceAdapter` Protocol — V2 adds new adapters, does NOT change the Protocol
- `ContentFetcher` for on-demand reading pane content — unchanged
- Textual Markdown widget in reading pane — unchanged

## Non-Goals (V2)

- OS push notifications (V3 — needs watchlists which are also V3)
- Watchlists / critical topic tracking (V3)
- Bookmarking / note-taking (V3)
- Tagging / categorization (V3)
- Export (JSON, CSV, markdown) (V3)
- Terminal image rendering (V3)
- Real ML model (embeddings, learned preferences) — V2 ships heuristic ranking; ML is a future FeedListStrategy swap
- Multi-user / auth / networked storage
- Mobile or web UI

## Acceptance Criteria

### A. Daemon
- [ ] `ai-dashboard daemon start` spawns a background process, writes PID to `~/.local/share/ai-dashboard/daemon.pid`, detaches from terminal
- [ ] `ai-dashboard daemon stop` sends SIGTERM, waits for clean shutdown, removes PID file
- [ ] `ai-dashboard daemon status` reports "running (pid NNNN)" or "stopped"
- [ ] `ai-dashboard daemon install` creates `~/Library/LaunchAgents/com.ai-dashboard.daemon.plist` with KeepAlive=true, loads it via launchctl
- [ ] `ai-dashboard daemon uninstall` unloads and removes the plist
- [ ] Daemon polls all configured sources on their intervals, writes to SQLite
- [ ] Daemon logs to `~/.local/share/ai-dashboard/daemon.log` (configurable log level)
- [ ] When daemon is running, TUI disables its own polling and reads from shared SQLite only
- [ ] When daemon is NOT running, TUI falls back to V1 foreground polling (backward compatible)
- [ ] Daemon process is the extracted V1 PollingOrchestrator running standalone
- [ ] Killing the daemon (SIGKILL) does not corrupt SQLite (WAL mode handles this)
- [ ] No items published on any configured source during a 24h period are missed in the DB (data completeness guarantee)

### B. New Sources
- [ ] Research phase produces a document (`.omc/research/v2-source-analysis.md`) evaluating ≥5 candidate sources with pros/cons/API details
- [ ] Lab blog adapter fetches RSS from ≥5 major AI labs (OpenAI, Anthropic, DeepMind, Google AI, Meta AI)
- [ ] Lab blog items are classified as source_kind="lab_blog" and tagged as 1st-party in the source taxonomy
- [ ] Reddit adapter fetches from ≥3 subreddits (r/MachineLearning, r/LocalLLaMA, r/singularity) via JSON API
- [ ] Reddit items include title, score, comment_count, author, subreddit, url, selftext
- [ ] Additional sources identified by research are implemented if viable (≥1 new source beyond lab blogs + Reddit)
- [ ] All new adapters implement the existing `SourceAdapter` Protocol with zero changes to the Protocol
- [ ] All new adapters have unit tests with recorded fixtures

### C. Search/Filter UI
- [ ] Source tabs appear above the feed list: All | AX | HN | GH | HF | NL | Reddit | Labs | ...
- [ ] Pressing number keys (1-9) switches tabs
- [ ] Each tab filters the feed list to that source_kind only; "All" shows everything
- [ ] Pressing `/` opens a text filter bar at the bottom of the feed list
- [ ] Typing in the filter bar narrows the current tab's items in real time (case-insensitive substring match on title + raw_payload summary/description)
- [ ] Pressing Escape closes the filter bar and restores the unfiltered view
- [ ] Filter is implemented as a `FilteredStrategy` decorator — does NOT modify the base strategy
- [ ] Tab state persists across item selection (selecting an item doesn't reset the tab)

### D. FeedListStrategy Implementations
- [ ] `BySourceStrategy(source_kind)` exists and returns items from one source only
- [ ] `HeuristicRankingStrategy` exists and sorts items by the heuristic score formula
- [ ] `FilteredStrategy(base, text_filter)` exists and filters any base strategy's output by text match
- [ ] Pressing `s` cycles between chronological and heuristic-ranked views
- [ ] All new strategies implement the existing `FeedListStrategy` Protocol with zero changes to the Protocol
- [ ] The V1 `ChronologicalAllSourcesStrategy` remains the default on "All" tab
- [ ] The `HeuristicRankingStrategy` is available via `s` key or a "Ranked" tab

### E. Heuristic Ranking
- [ ] Score formula: `engagement_normalized + source_weight + keyword_boost + recency_decay - skip_penalty`
- [ ] `engagement_normalized` is per-source: `min(value / percentile_95_for_that_source, 1.0)`
- [ ] 1st-party sources (arXiv, lab blogs) get `source_weight = +0.3`; community sources get `+0.0`
- [ ] `keyword_boost = +0.2` per match with user's top 10 most-frequent search terms
- [ ] `recency_decay = e^(-hours_old / 24)` — 24h half-life
- [ ] `skip_penalty = -0.1` per time `source_kind` was skipped (not viewed) in last 50 item views
- [ ] All weights are configurable via `config.toml` `[ranking]` section
- [ ] New DB tables: `user_search_history(term TEXT, count INTEGER, last_used TEXT)`; `item_view_log(source_kind TEXT, source_uid TEXT, action TEXT, timestamp TEXT)`
- [ ] Selecting an item in the feed list records a `viewed` action; scrolling past without selecting records `skipped`
- [ ] A 1st-party item with high engagement ranks above a community item with the same engagement (source weight test)

### F. Backward Compatibility
- [ ] V1 behavior is fully preserved when daemon is not running
- [ ] Existing V1 config.toml files work without modification (new sections are optional with defaults)
- [ ] V1 SQLite database is forward-compatible (new tables added via migration, existing tables unchanged)
- [ ] All 41 existing V1 tests continue to pass

## Assumptions Exposed & Resolved

| # | Assumption | Challenge | Resolution |
|---|---|---|---|
| 1 | All 15 deferred items are V2 | R1 — forced priority selection | 9 selected, then further split: 5 V2, 4 V3 |
| 2 | V2 needs all 9 items at once | R2 — V2/V3 split | V2 = daemon + sources + search + strategies + ranking; V3 = watchlists, bookmarks, tags, images |
| 3 | Daemon is needed for warm cache UX | R4 Contrarian — challenged 10s bootstrap | Real reason is continuous data collection / historical completeness, not startup speed |
| 4 | ML ranking needed in V2 | R6 Simplifier — proposed heuristic alternative | Heuristic ranking for V2; ML deferred as future FeedListStrategy swap |
| 5 | Twitter is a must-have source | R7 — probed source specifics | Deferred to research phase; may be Twitter, Bluesky, or something else |
| 6 | Source selection is predetermined | R7 — user response | Research phase required before implementation to identify best sources |
| 7 | Ranking formula needs ML | R9 — proposed concrete formula | Formula approved: engagement + source_weight + keyword_boost + recency_decay - skip_penalty |

## Technical Context (Brownfield)

V1 codebase at `/Users/dev/projects/dashboard`:
- 5 source adapters (arXiv, HN, GitHub Trending, HuggingFace, Newsletter)
- `PollingOrchestrator` with asyncio.Event wake + bootstrap fetch + 2s shutdown SLO
- `FeedListStrategy` Protocol with AST-enforced pluggability invariant (verified by tests)
- `SourceAdapter` Protocol with factory registry in `sources/__init__.py`
- SQLite WAL mode, single-connection per process
- Textual Markdown widget reading pane with on-demand content fetching (ContentFetcher)
- 41 passing tests

Key V1 seams that V2 builds on:
- `FeedListStrategy` Protocol → add `BySourceStrategy`, `HeuristicRankingStrategy`, `FilteredStrategy`
- `SourceAdapter` Protocol + factory → add Reddit, lab blog, research-identified adapters
- `PollingOrchestrator` → extract to standalone daemon process
- `Database` → add `user_search_history`, `item_view_log`, `schema_version` migration for v2

## Interview Transcript

<details>
<summary>Full Q&A (9 rounds)</summary>

### Round 1
**Q:** Of the 15 deferred items, which ones would change your daily behavior?
**A:** 9 items selected (all except OS push notifications and export)
**Ambiguity:** 82.5%

### Round 2
**Q:** Assign each to V2 or V3.
**A:** V2: daemon, sources, search, strategies, ML ranking. V3: watchlists, bookmarks, tags, images.
**Ambiguity:** 69.2%

### Round 3
**Q:** If V2 shipped only ONE feature, which makes it worth releasing?
**A:** Persistent daemon + warm cache.
**Ambiguity:** 60.8%

### Round 4 (Contrarian)
**Q:** Is the 10s bootstrap gap really worth a full daemon?
**A:** The real reason is continuous data collection — never missing items between sessions.
**Ambiguity:** 51.5%

### Round 5
**Q:** How should the daemon stay alive?
**A:** Both CLI-managed for dev + launchd plist for production.
**Ambiguity:** 43.8%

### Round 6 (Simplifier)
**Q:** Does V2 need real ML, or would heuristic ranking suffice?
**A:** Start with heuristics, add ML as a FeedListStrategy later.
**Ambiguity:** 37.2%

### Round 7
**Q:** Concrete scope for new sources (Reddit, Twitter, lab blogs)?
**A:** 1st-party sources (arXiv, lab blogs) weighted higher. Research phase needed to identify best sources. Twitter deferred to research evaluation.
**Ambiguity:** 30.8%

### Round 8
**Q:** What does the search UI look like?
**A:** Source tabs + text filter combined. Tabs for per-source views, `/` for text filtering within any tab.
**Ambiguity:** 23.1%

### Round 9
**Q:** Heuristic ranking formula — does this capture your intent?
**A:** Yes — engagement + source_weight + keyword_boost + recency_decay - skip_penalty. Ship it.
**Ambiguity:** 15.0%

</details>
