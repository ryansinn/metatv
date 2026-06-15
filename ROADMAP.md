# MetaTV Roadmap

What's left to build. Completed features live in git history.

> **Product vision & direction:** see [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) for the
> enduring "why" — the thesis (lean native ambient-companion player; complexity → a mind-reading
> Discover; comfort↔explore and chef↔grocery axes), design principles (function-over-form,
> power-without-dumbing-down, good-on-raw-data), and clearly-subordinate stretch directions
> (multi-source aggregation, URL-loaded plugin manifests, headless backend + mobile/TV clients).
> The items below are concrete, tracked features.

## Metadata & Enrichment

- [~] **Genre normalization to canonical English** — `_GENRE_NORM` dict in `metatv/core/repositories/channel.py` normalizes French, German, Spanish, Italian, Dutch, and Arabic genres at query time (applied in `get_prefix_stats` and `normalize_genre()`). Arabic variants added 2026-06-05. Remaining gaps: Chinese, Japanese, Persian, Hindi script genres; a live-DB sanity scan to surface high-volume unrecognized genres should be added as a developer tool or CI check. Display text remains the raw provider value; the i18n layer (future) translates canonical English → user locale in the other direction.
- [ ] **TMDb / OMDb providers** — architecture in place; need API key config UI + implementations
- [ ] **Xtream VOD API enhancement** — use `get_vod_info()` / `get_live_info()` for full metadata instead of basic stream list
- [ ] **Episode-level metadata** — extract from series_info response; show in details pane per episode
- [ ] **Background metadata enrichment** — queue-based async fetching for entire library with progress tracking
- [ ] **Plugin config UI** — enable/disable providers, API keys, priority order, cache management, test connections
- [ ] **Channel name parser** — extract title, year, quality markers (ᴴᴰ, ᵁᴴᴰ), strip category headers

## EPG

- [~] **EPG settings UI** — per-provider EPG enable/disable, XMLTV URL override, refresh-interval throttle dropdown, and guide-freshness display are now in the source editor (#14). Global default refresh interval dropdown added to Settings dialog. Remaining config-file-only: notification minutes-before, filler-match patterns, and the global auto-refresh toggle.
- [ ] **Watchlist persistence** — store watchlist entries in database instead of memory-only; enable watchlist survival across app restarts and multi-device sync (future)
- [ ] **Compressed XMLTV** — gzip decompression for `.xml.gz` feeds via `gzip.open()` on response stream
- [ ] **EPG data cleanup** — auto-delete `EpgProgramDB` rows where `stop_time < now - 24h` to prevent unbounded DB growth
- [ ] **EPG content-type filter** — classify channels by name keywords (Sports/News/Kids/Movies/Music) since ProSat has no `<category>` tags; add `[All Types ▼]` dropdown in EPG header
- [ ] **Right-click context on On Now rows** — "Hide show globally", "Add to watchlist", "Dismiss channel for 7 days"
- [ ] **Channel-specific watchlist** — per-channel keyword entries alongside global patterns; two-tier Watchlist tab
- [ ] **Watchlist match prioritization** — when a keyword matches many channels (e.g. "fifa world cup" → 40+), currently the display is arbitrary. Apply ranking: (1) highest quality (4K > FHD > HD > SD), (2) previously-watched channels float up, (3) user can hide/demote individual entries. Also add a "Show all in Search" button on the watchlist keyword card title to jump to the Search tab pre-filled with the keyword, showing all matching results without the card display limit.
- [x] **Watchlist layout** — greedy 2-column layout implemented (2026-06-13): cards assigned to the shorter column using live match-count as height proxy; FIFA World Cup no longer monopolizes one column while the other sits empty. `_MAX_GROUPS = 4` cap prevents a single card from dominating full column height.
- [x] **EPG Events tab** — platform-event channels (`special_view='live_event'`) surfaced in a new Events tab inside the EPG view (#17, 2026-06-14): Timeline sub-view (on-now/upcoming/passed groups) and By-Network sub-view with a network filter; both sub-views persist. `LiveEventDTO` + `ChannelRepository.get_live_events_dto()`.
- [ ] **EPG Browse/Search view makeover** — restyle the Browse tab's search/filter UI to match the main Search chip view: clean title display using `detected_*` fields, quality badges, source indication. Candidate columns: Category | Channel | Quality | Source emoji | Show | Duration. Also align the Browse time-format and result-count footer with the On Now tab style.
- [ ] **Guide channel player** — embedded mpv in EPG view (50/50 split), autoplay on channel browse with debounce
- [ ] **Collapsible category groups in On Now** — group rows by channel prefix, allow collapse/expand; replace region dropdown
- [ ] **Clear EPG link action** — 🧹 dustbroom button in channel details pane (and right-click in channel list) to sever a bad EPG assignment: sets `channel_db_id = NULL` on all `epg_programmes` rows for that channel and clears `epg_channel_id`. Needed because fuzzy channel matching produces wrong links (e.g. `EAR ★ The Simpsons` matched to `UandEden.uk`). All EAR ★ channels are currently mis-matched — they're 24/7 show-loop channels that got paired with unrelated UK/EU broadcast channels whose XMLTV display-names collide.
- [ ] **EPG fuzzy match — region-gating** — before accepting a fuzzy (display-name) match, check that the channel's detected region prefix and the EPG channel ID's country TLD are compatible (e.g. `EAR`/`UK`/`EN` → accept `.uk`/`.us`/`.ca`, reject `.es`/`.de`). Also consider blocklisting prefix groups (EAR, 24/7) from fuzzy matching entirely since they're not real broadcast channels.
- [ ] **EPG accuracy flagging** — per-channel "unreliable EPG" flag; stores mismatch reports; shown in Hidden view and details pane
- [ ] **AI-assisted mismatch analysis** — export accumulated flags to Claude API with context; model identifies failure pattern and suggests corrected `epg_channel_id` mapping

## Playback & Queue

- [ ] **Ambient mini-player mode** — low-chrome, always-on-top / PIP corner window that expands to fullscreen; the "media in the corner while working ↔ relax fullscreen" continuum (see PRODUCT_VISION.md ambient-companion thesis)
- [ ] **Global playback hotkeys** — control play/pause/next/seek without focusing the player window (essential for the corner-companion loop)
- [ ] **Music as a first-class media type** — treat audio/music alongside video in management, queue, and playback (MetaTV is a media *and* music player)
- [ ] **(Stretch) Desktop-embedded video-widget playback** — Linux/KDE: render playback into a desktop-embedded widget that normal windows cover when on top (wallpaper/widget-style ambient playback); platform-specific, experimental
- [ ] **MPV IPC event system** — monitor `playlist-pos`, `time-pos`, `end-file` via socket; thread-safe Qt signals; enables real-time history for queued episodes and resume playback
- [ ] **Resume playback** — track `time-pos` per episode; "Resume from X:XX?" prompt on re-open (requires IPC event system)
- [ ] **Completion detection** — auto-mark watched at >90%; mark partial if 10–90% (requires IPC event system)
- [ ] **Progress bars** — colored watch-progress bar under episode items (green=done, yellow=partial, gray=unwatched)
- [ ] **"Play Next Episode" button** in history sidebar — finds next unwatched after last played

## Series & Episodes

- [ ] **Episode/Season favorites** — `is_favorite` on EpisodeDB/SeasonDB; right-click to favorite; drill-down from favorites sidebar
- [ ] **Smart series cache refresh** — background check for new episodes; incremental updates only; visual "Checking..." indicator
- [ ] **Episode title deduplication** — strip redundant series-name prefix from tree view (configurable via `show_full_episode_titles`)
- [ ] **Cross-source episode completeness tool** — compare season/episode counts across providers per title; extend `scripts/inspect_series.py` with `--live` flag

## Discovery & Recommendations

- [ ] **Channel-level deduplication** — group quality variants into a single item with quality selector (reduce 240k → ~20-30k unique titles); separate from cross-source recommendation dedup already implemented
- [ ] **Related content suggestions** — in details pane, beyond current Similar Titles lightbox
- [ ] **Trending content** — requires external data feed
- [ ] **Canonical content IDs (TMDb/IMDb)** — once TMDb provider is wired, use `tmdb_id` / `imdb_id` as the primary dedup key; current `(norm_title, media_type, year, director)` fingerprint is a stopgap with known false-split risks (see CLAUDE.md § Content dedup)
- [ ] **Dedup transparency toggle** — advanced/debug setting to bypass recommendation dedup and see raw scored candidates; paired with a "why was this recommended?" explainer; useful for diagnosing cases where the heuristics make bad assumptions
- [ ] **AI-powered personalization from user categories** — once an LLM provider is wired (Claude API / local), use user category names + mood signals + watch history to generate natural-language taste profiles ("you prefer slow-burn character dramas, avoid reality TV") that feed the recommendation engine; category mood weights become the training signal
- [ ] **User category genre/type contextualization** — after creation, the recommendation dashboard can surface "Your 'Quranic Recitations' category is tagged Religious/Music — adjust how it influences recommendations?"; the engine infers genre from existing channel metadata, user just confirms or overrides; intentionally deferred from creation dialog to reduce friction
- [ ] **Discovery shelves from user categories** — extend user-category shelves with "More like this category" auto-generated sub-shelves; if user created "Korean Drama" with Like mood, auto-generate a "More Korean Drama" shelf from unassigned Korean channels matching genre overlap

## UI / UX

- [ ] **UI vocabulary standard** — define one canonical term per action across all surfaces: "Exclude" for filter/suppression (panel or global), "Hide" for per-channel hiding, retire "Block" as a synonym; document in UI_UX_GUIDELINES.md and enforce in new UI code
- [ ] **Context menu standardization** — define a standard context menu structure for right-clicking on any channel or filter item; currently each view (channel list, EPG, details pane, filter panel, discover) has its own ad-hoc menu; centralize into a shared model
- [~] **"Search this title" context menu action** — right-click on any channel list item populates the search box with `channel.detected_title`. Falls back to `channel.name` if `detected_title` is null. Partially landed: double-clicking a queue/favorites entry for an unavailable (expired/disabled) source opens Search pre-filled with the stripped title (#16, 2026-06-14). Right-click context-menu version on active channels is still open.
- [ ] **"Copy title to clipboard" context menu action** — right-click copies `channel.detected_title` (or `channel.name` fallback) to the system clipboard via `QApplication.clipboard().setText(...)`. Zero side effects, useful for pasting titles into search engines or sharing. Both this and "Search this title" belong in `_show_context_menu_for` in `main_window_favorites.py`.
- [ ] **Unified filter panel across views** — EPG, Discover, and Recommended each have their own filter controls; goal is a single FilterPanel (or shared filter state) across all views; migrate EPG sports filter bar, discover chips, recommendations filter to the same pattern; deprecate the legacy "quick filter" bar where it still appears
- [ ] **Uncategorized prefix audit** — classify GO, CITY, V+, ONE, SU, VD, SKR, BEE, TY, RD, RG, RX, PLAYER, TF, CON, LSV, TEN, TK, BLUE, GEN, NIC, FZ, LUX, PN, TGK, CRB, EST into known groups; user is actively building the mapping
- [ ] **Settings page architecture** — Settings mode using the three-panel layout (left nav / center controls / right contextual help); sections: General, Providers, Players, Metadata, EPG, Filters, Display, Keyboard, Notifications, Advanced
- [ ] **Filter system improvements** — search within excluded results for 50k+ filtered datasets; provider-level filtering when multiple providers active
- [ ] **User-defined prefix groups** — UI to assign "Other" prefixes to existing groups or new custom groups (e.g. promote "ARAB" → Arabic, or create "My Sports" = [ESPN, DAZN]); backed by `user_prefix_overrides` config already in place; "Reset to defaults" clears overrides and reverts all prefixes to built-in group mappings
- [ ] **"Copy filters from…" across views** — apply a Tier 1 filter from one view (Search/Discover/EPG) to another; small dropdown on each filter bar
- [ ] **"Promote to global exclusion"** — convert a dialed-in Tier 1 view filter into a Global Exclusion (requires inversion: everything NOT selected becomes excluded); useful when you've found a good filter config and want to make it permanent
- [ ] **Grid view** for channel list
- [ ] **Keyboard shortcuts** — Ctrl+F focus search, arrow key nav, Esc clear search
- [ ] **Dark mode / theme selection**
- [ ] **Embedded player** option (split-pane mpv in-app)
- [ ] **Channel sub-attributes / session type tags** — bracket suffixes like `[FP1]`, `[RACE]`, `[SPRINT]`, `[Prelims]`, `[Main Card]`, `[EVENT ONLY]` encode valuable sub-category data (Formula 1 session type; UFC/combat sports segment). No DB field exists today to store these — they're left in the bare channel title for now. Needs a `channel_tags` or `session_type` JSON column so sessions can be filtered ("show me only F1 Race rounds, not practice"). Related: `[WEST]`/`[EAST]` US regional variants would also benefit from a sub-region field.
- [ ] **Episode history tracking fix** — debug logging to trace why parent channel lookup sometimes fails for history updates
- [ ] **Restore ratings display in details pane** — the 👍/👎 rating controls have gone missing from the details panel; re-add them to the details pane layout. Bug: was present, now absent.
- [ ] **Details pane — move "Source:" beneath title/year** — relocate the Source field (currently below the metadata block) to the right side of the title row, inline with or directly beneath the title + year line; keeps the primary content area cleaner and puts provenance info near the header where it's most useful
- [ ] **Launch-time feedback prompts** — while channels load at startup (5-10s), show "You watched [X] — what did you think?" prompts for recently-watched content with no rating; feeds the recommendation engine quickly; opt-in ("Ask me about content I watch"), explain data stays local; dismissable and rate-limited so it doesn't become annoying
- [ ] **Recommendation dashboard — category mood editor** — show all user categories with their current mood, channel count, and inferred genre; let user adjust mood in bulk without re-opening CategoryPickerDialog; "Why is this recommended?" explainer links back to category mood contributions

## Code Health / Refactor

See **[docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md)** for the full prioritized,
file:line-level task list (full-codebase review 2026-06-01).

**Bands 1–6 complete** (2026-06-01 → 06-05; details in git history): P0 best-practice bug fixes,
P1/P4 deduplication, Band 3 structural fixes (session_scope, closeEvent registry, JSONEncoded,
icons.py, EPG conversion boundary), P2 inline-styles → `theme.py` tokens, P3 file splits
(`sidebar_sections` → `gui/sidebar/`, `filter_panel` → `filter_group_row`, `provider_editor` →
`provider_probe` + `url_row_widget`), and Band 6 — `main_window.py` passes 2–4 (nav/metadata/
favorites mixins, 3950 → 2457), off-thread streaming, status-set dedup (merged as PR #7 squash
`2e7ef5b`; 291 tests). Open:

- [x] **Band 7 — responsiveness seam + finish decomposition** (merged 2026-06-13): `_run_query` async-read seam + repository DTOs (B7-1/2); EPG count, series tree, sidebar refresh (Favorites/History/Queue) off-thread (B7-3…B7-6); session_scope migration for main_window_favorites/metadata mixins. `load_channels` (B7-bespoke), epg_view tab split, and channel.py repo split deferred → see Band 9. See **[docs/REFACTOR_PLAN_BAND7.md](docs/REFACTOR_PLAN_BAND7.md)**.
- [x] **Band 8 — seam cleanup + per-provider EPG config + EPG Events tab** (merged 2026-06-14): B8-1 N+1→batch in `build_history_dtos`; B8-2 DTO imports hoisted to module scope; B8-3 read-only seam uses `commit=False`; B8-5 `BackgroundRefreshMixin` unifies sidebar async pattern; B8-7 `WatchAlertsSection` migrated to mixin (off-thread, N+1 batched). Deferred: B8-4 (`load_channels`→seam) and B8-6 (expunge→DTO) require a display to smoke-test → carried into Band 9. See **[docs/REFACTOR_PLAN_BAND8.md](docs/REFACTOR_PLAN_BAND8.md)**.
- [ ] **Band 9 — deferred seam items + EPG cosmetic cleanup** (planned): B9-1 `load_channels`→seam, B9-2 expunge→DTO in favorites/metadata mixins, B9-3 EPG cosmetic cleanups (dead local import, dormant view files, hex literal in alerts). See **[docs/REFACTOR_PLAN_BAND9.md](docs/REFACTOR_PLAN_BAND9.md)** (draft pending Opus review).
- [ ] **Exclusions chip dead zone** (B7-11) — text area of the Exclusions chip is not clickable at cold launch; becomes clickable after a notification appears/dismisses. Root cause unknown: `setCheckable(False)` and solid-fill hover did NOT fix it. Likely z-order/geometry-timing in the bottom nav bar at startup; investigate `notification_widget.py` show/hide side-effects + bottom-nav-bar layout init.

## Data & Storage

- [ ] **Image cache size cap + LRU eviction** — `~/.cache/metatv/images/` currently has no hard cap and grows indefinitely. Implement: configurable max size (default 500MB; settings UI control); eviction strategy = LRU (by file atime or a lightweight manifest); also prune images whose URL-derived key matches a provider that has since been removed. Current size can exceed 1GB+ with long-term use.
- [ ] **Quality token display refinement** — `HEVC` and `RAW` are codec/bitrate descriptors, not viewer-facing quality levels; they appear in the On Now quality column and filter chips but are not meaningful to most users. Consider translating: `HEVC` → omit or show as a small "efficient" badge; `RAW` → omit or show as "Uncompressed". Do not rename them in the DB (they're derived from channel names) — apply a display-layer translation only.

## Platform & Distribution

- [ ] **M3U playlist support**
- [ ] **Windows / macOS packaging** (AppImage / Flatpak for Linux too)
- [ ] **Multi-language UI** — i18n via Qt Linguist / gettext; RTL layout support for Arabic/Hebrew; locale-aware date/time formatting
- [ ] **Plugin system** for community providers

---

## Next Up

1. TMDb / OMDb provider implementations (architecture ready — `metatv/metadata_providers/`, `MetadataManager` chain)
2. EPG settings UI (notification minutes-before, filler patterns, auto-refresh toggle)
3. Resume playback via MPV IPC event system
