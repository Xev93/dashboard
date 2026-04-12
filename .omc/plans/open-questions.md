# Open Questions

## ai-dashboard-v2-plan - 2026-04-12

- [ ] **Lab blog RSS feed URLs**: The default URLs in Task 4.1 are best-guesses. Research phase (Phase 3) or a quick validation task should confirm current working URLs for all 5 labs before the adapter is implemented. — Some labs change their RSS feed URLs without notice.

- [ ] **Reddit User-Agent policy**: Reddit's rate limiting behavior for their free JSON API is undocumented. The adapter uses a descriptive UA but may still hit limits. — If rate limiting is severe, consider adding OAuth2 app-only auth (free, higher limits) as a follow-up.

- [ ] **Engagement percentile cold start**: On a fresh install with few items, the p95 computation for `engagement_normalized` may be unreliable (e.g., 10 items → p95 is the 10th item). — Consider requiring a minimum sample size (e.g., 20 items) before using DB-computed percentiles; fall back to hardcoded estimates otherwise.

- [ ] **"Skipped" definition precision**: Task 7.1 defines "skipped" as items between the previous and current cursor position. This may over-count if the user scrolls quickly or uses page-down. — Consider debouncing or only counting items visible for >1 second as "skipped". The spec says "scrolling past without selecting" which is ambiguous about speed.

- [ ] **Phase 4.8 scope**: The research-identified adapter depends entirely on Phase 3 output. If research finds no viable additional source, this task becomes a no-op. — The spec requires "≥1 new source beyond lab blogs + Reddit" (AC B.6), so the research phase must produce at least one recommendation.

- [ ] **macOS launchctl version compatibility**: `launchctl load` is deprecated on newer macOS (14+) in favor of `launchctl bootstrap`. — Consider detecting macOS version and using the appropriate command, or documenting the limitation.

- [ ] **`busy_timeout` PRAGMA**: Risk 1 mentions `PRAGMA busy_timeout = 5000` but the current `Database.connect()` doesn't set it. — This should be added in Phase 1 or Phase 2 as a prerequisite for safe concurrent access.
