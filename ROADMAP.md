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

- [ ] **EPG settings UI** — notification minutes-before, filler patterns, auto-refresh toggle (currently config-file-only)
- [ ] **Compressed XMLTV** — gzip decompression for `.xml.gz` feeds via `gzip.open()` on response stream
- [ ] **EPG data cleanup** — auto-delete `EpgProgramDB` rows where `stop_time < now - 24h` to prevent unbounded DB growth
- [ ] **EPG content-type filter** — classify channels by name keywords (Sports/News/Kids/Movies/Music) since ProSat has no `<category>` tags; add `[All Types ▼]` dropdown in EPG header
- [ ] **Right-click context on On Now rows** — "Hide show globally", "Add to watchlist", "Dismiss channel for 7 days"
- [ ] **Channel-specific watchlist** — per-channel keyword entries alongside global patterns; two-tier Watchlist tab
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
file:line-level task list (full-codebase review 2026-06-01). Summary:

- [x] **P0 — best-practice bug fixes** — all 4 done (2026-06-01, branch refactor/p0-correctness-bugs): session leak fix, EPG browse TZ fix, closeEvent shutdown calls, view lifecycle on_deactivate
- [x] **P1 — deduplication** — all 5 done (2026-06-01): parse_provider_urls helper, _apply_favorite_toggle, config icons, import hoisting, executor thread leak fix
- [x] **Band 3 — structural fixes** — all done (2026-06-01, branch refactor/band3-structural): WAL (was already on), closeEvent registry, session_scope(), JSONEncoded TypeDecorator, icons.py, EPG conversion boundary + 2 latent bug fixes; 134 tests
- [x] **P2 — inline stylesheets → `theme.py`** — all 7 files done (2026-06-01, branch refactor/band4-styles): epg_view (63 calls), provider_editor (36), global_filter_dialog (30), similar_lightbox (24), filter_panel (23), sidebar_sections (19), details_sections (17); theme.py grew from 7 → 32 constants
- [~] **P3 — decompose oversized files (>1000-line rule)** — partial (2026-06-04, branch refactor/band6, PR #7):
  - [x] `sidebar_sections.py` (1402) → `gui/sidebar/` package (6 files, shim stays for compat)
  - [x] `filter_panel.py` (1064) → `gui/filter_group_row.py` (483 lines) + `filter_panel.py` (597 lines)
  - [x] `provider_editor.py` (1121) → `core/provider_probe.py` + `gui/url_row_widget.py`; down to 948 lines
  - [~] `main_window.py` (3950 at B6 start) → passes 2–4 done (B6-1): nav/metadata/favorites extracted to 3 new mixins; down to **2457 lines**, 88 methods. Pass 5 needed: extract _ChannelLoadMixin (~500 lines load_channels/bg_load/on_channels_loaded) + _SeriesMixin (~500 lines series/episode) to reach <1000.
  - [ ] `epg_view.py` (2157) → tab split (B6-2) deferred to dedicated session; requires GUI smoke-test (90+ methods, deeply coupled cross-tab state: shared worker, _data signal, timers)
- [x] **P4 — status-set dedup** (B6-3, 2026-06-04): audited 5 sites — legitimately different sets for different purposes; added `WatchQueueRepository.get_queued_ids()` helper used at 3 call sites; `--help` artifact confirmed absent
- [x] **Band 6 cleanups** (2026-06-04, PR #7): B6-7 stream validation off UI thread (play_media non-blocking), B6-8 session_scope in streaming, B6-9 hoisted imports, B6-10 unit tests for provider_probe + _format_probe_message (19 new tests, 196 total)
- [ ] **Exclusions chip dead zone** — text area of the Exclusions chip is not clickable at cold launch; becomes fully clickable after a notification appears and dismisses. Root cause unknown: `setCheckable(False)` and solid-fill hover styles did NOT fix it. Likely a z-order or geometry-timing issue in the bottom nav bar at startup. Needs investigation of `notification_widget.py` show/hide side-effects and bottom nav bar layout initialisation.

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
