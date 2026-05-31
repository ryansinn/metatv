# MetaTV Roadmap

What's left to build. Completed features live in git history.

## Metadata & Enrichment

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
- [ ] **EPG accuracy flagging** — per-channel "unreliable EPG" flag; stores mismatch reports; shown in Hidden view and details pane
- [ ] **AI-assisted mismatch analysis** — export accumulated flags to Claude API with context; model identifies failure pattern and suggests corrected `epg_channel_id` mapping

## Playback & Queue

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

## UI / UX

- [ ] **Settings page architecture** — Settings mode using the three-panel layout (left nav / center controls / right contextual help); sections: General, Providers, Players, Metadata, EPG, Filters, Display, Keyboard, Notifications, Advanced
- [ ] **Filter system improvements** — search within excluded results for 50k+ filtered datasets; provider-level filtering when multiple providers active
- [ ] **User-defined prefix groups** — UI to assign "Other" prefixes to existing groups or new custom groups (e.g. promote "ARAB" → Arabic, or create "My Sports" = [ESPN, DAZN]); backed by `user_prefix_overrides` config already in place; "Reset to defaults" clears overrides and reverts all prefixes to built-in group mappings
- [ ] **"Copy filters from…" across views** — apply a Tier 1 filter from one view (Search/Discover/EPG) to another; small dropdown on each filter bar
- [ ] **"Promote to global exclusion"** — convert a dialed-in Tier 1 view filter into a Global Exclusion (requires inversion: everything NOT selected becomes excluded); useful when you've found a good filter config and want to make it permanent
- [ ] **Grid view** for channel list
- [ ] **Keyboard shortcuts** — Ctrl+F focus search, arrow key nav, Esc clear search
- [ ] **Dark mode / theme selection**
- [ ] **Embedded player** option (split-pane mpv in-app)
- [ ] **Episode history tracking fix** — debug logging to trace why parent channel lookup sometimes fails for history updates

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
