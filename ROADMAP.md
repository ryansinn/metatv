# MetaTV Roadmap

What's left to build. Completed features live in git history.

> **Product vision & direction:** see [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) for the
> enduring "why" — the thesis (lean native ambient-companion player; complexity → a mind-reading
> Discover; comfort↔explore and chef↔grocery axes), design principles (function-over-form,
> power-without-dumbing-down, good-on-raw-data), and clearly-subordinate stretch directions
> (multi-source aggregation, URL-loaded plugin manifests, headless backend + mobile/TV clients).
> The items below are concrete, tracked features.

## Metadata & Enrichment

- [~] **Genre normalization to canonical English** — `_GENRE_NORM` dict in `metatv/core/repositories/channel.py` normalizes French, German, Spanish, Italian, Dutch, and Arabic genres at query time (applied in `get_prefix_stats` and `normalize_genre()`). Arabic variants added 2026-06-05. **Details-pane genres normalized v0.26.0 (#294)** — the pane rendered whatever language the provider sent ("Dramma", "Drame / Mystère"), so the same genre read differently per source; it now goes through the same canonicalizer as everywhere else, and filtered variants became clickable. Remaining gaps: Chinese, Japanese, Persian, Hindi script genres; a live-DB sanity scan to surface high-volume unrecognized genres should be added as a developer tool or CI check. Display text remains the raw provider value; the i18n layer (future) translates canonical English → user locale in the other direction.
- [x] **TMDb / OMDb providers** — SHIPPED v0.23.0 (#395): `metadata_providers/tmdb.py` + `omdb.py`, and the previously-orphaned `metadata_enabled`/`metadata_auto_fetch`/`metadata_enabled_providers`/`metadata_provider_priority` config is now actually consumed (a one-time migration merges the new provider names into existing installs, else a pasted key was a silent no-op). **UNVERIFIED AGAINST A LIVE API** — built and tested against mocked aiohttp only; no key was available. Acceptance test owed: paste key → Settings *Test* → enrich one title. *(A provider-native TMDb-id enrichment path already ships — `tmdb_enrichment_manager.py` harvests the id your provider returns from `get_vod_info`, no key required; this item is the external TMDb/OMDb API lookups for posters/plot beyond what your provider carries.)*
- [~] **Xtream VOD API enhancement** — `get_vod_info()` is already called lazily by `tmdb_enrichment_manager.py` to harvest the provider's own TMDb id. Remaining: `get_live_info()`, and using the full VOD payload for metadata beyond the id.
- [x] **Episode-level metadata** — SHIPPED v0.23.0 (#393): `plot`/`air_date`/`rating`/`still_url` lifted at ingestion from the episode blob already stored in `EpisodeDB.raw_data`, with a no-network backfill for existing rows. No API key needed — the data was on disk and being discarded.
- [x] **Background metadata enrichment** — SHIPPED v0.23.0 (#398): `core/metadata_enrichment_queue.py`, single worker, engagement-first ordering resolved in SQL, hidden providers excluded, migration-deference, bounded retries with visible failure counts, Tools view with start/pause/resume/cancel. Opt-in (`metadata_background_refresh` defaults False).
- [~] **Plugin config UI** — SHIPPED v0.23.0 (#395/#246): the "Metadata & API Keys" settings section carries masked TMDb/OMDb key fields, enable/disable, priority order, and per-key **Test** buttons (`settings_dialog_tabs.py:486`). Remaining: cache management controls.
- [~] **Channel name parser** — SHIPPED: title/year/quality/region/prefix are extracted at ingestion into the stored `detected_*` fields (`update_detected_prefixes()`). **Trailing-actor names kept v0.26.0 (#285)** — sources that append a performer ("Adaptation. 4K (2002) NICOLAS CAGE") had that trimmed off the display *and* discarded entirely, losing a real cast signal; it is now captured rather than thrown away. Remaining debt: ~1850 scene-release VOD rows keep the release filename as `detected_title` (cut at the resolution token at ingestion). This matters more than it looks — `content_key`, dedup, search and tag decomposition all read `detected_title`, so parser debt degrades dedup/search/recs even while TMDb-enriched *displays* look clean.

## EPG

- [~] **EPG settings UI** — per-provider EPG enable/disable, XMLTV URL override, refresh-interval throttle dropdown, and guide-freshness display are now in the source editor (#14). Global default refresh interval dropdown added to Settings dialog. **Notification minutes-before and the global auto-refresh toggle SHIPPED v0.18.0 (#207).** Remaining config-file-only: filler-match patterns.
- [~] **Watchlist persistence** — watchlist entries are **config-persisted** and already survive restarts (this line's "memory-only" premise was stale). Remaining: move them to the database proper, which is what multi-device sync (future) would need.
- [x] **Compressed XMLTV** — SHIPPED v0.18.0 (#207): automatic detection via magic bytes, `.gz` URL, or `Content-Encoding: gzip`; a corrupt gzip stream degrades to a partial guide rather than losing the fetch (`xmltv_parser.py`).
- [x] **EPG data cleanup** — SHIPPED v0.18.0 (#207): after every successful guide fetch, programmes expired more than a day ago (configurable) are swept across ALL sources, including sources that have stopped refreshing.
- [x] **EPG content-type filter** — SHIPPED v0.18.0 (#210) in EPG On Now.
- [ ] **Watchlist match prioritization** — when a keyword matches many channels (e.g. "fifa world cup" → 40+), currently the display is arbitrary. Apply ranking: (1) highest quality (4K > FHD > HD > SD), (2) previously-watched channels float up, (3) user can hide/demote individual entries. Also add a "Show all in Search" button on the watchlist keyword card title to jump to the Search tab pre-filled with the keyword, showing all matching results without the card display limit.
- [x] **EPG Browse/Search view makeover** — SHIPPED v0.18.0 (#212). Original spec: restyle the Browse tab's search/filter UI to match the main Search chip view: clean title display using `detected_*` fields, quality badges, source indication. Candidate columns: Category | Channel | Quality | Source emoji | Show | Duration. Also align the Browse time-format and result-count footer with the On Now tab style.
- [ ] **Guide channel preview** — autoplay-on-browse preview while scrubbing the guide (debounced). Plays into the **external** companion mpv window (NOT embedded in the EPG view) — playback stays separate from the management UI per the product's management/playback-separation principle.
- [x] **Collapsible category groups in On Now** — SHIPPED v0.18.0 (#211).
- [x] **Clear EPG link action** — SHIPPED v0.18.0 (#208). Original spec: 🧹 dustbroom button in channel details pane (and right-click in channel list) to sever a bad EPG assignment: sets `channel_db_id = NULL` on all `epg_programmes` rows for that channel and clears `epg_channel_id`. Needed because fuzzy channel matching produces wrong links (e.g. `EAR ★ The Simpsons` matched to `UandEden.uk`). All EAR ★ channels are currently mis-matched — they're 24/7 show-loop channels that got paired with unrelated UK/EU broadcast channels whose XMLTV display-names collide.
- [x] **EPG fuzzy match — region-gating** — SHIPPED v0.18.0 (#209), including skipping show-loop channels. Original spec: before accepting a fuzzy (display-name) match, check that the channel's detected region prefix and the EPG channel ID's country TLD are compatible (e.g. `EAR`/`UK`/`EN` → accept `.uk`/`.us`/`.ca`, reject `.es`/`.de`). Also consider blocklisting prefix groups (EAR, 24/7) from fuzzy matching entirely since they're not real broadcast channels.
- [ ] **EPG accuracy flagging** — per-channel "unreliable EPG" flag; stores mismatch reports; shown in Hidden view and details pane
- [ ] **AI-assisted mismatch analysis** — export accumulated flags to Claude API with context; model identifies failure pattern and suggests corrected `epg_channel_id` mapping

## Playback & Queue

- [ ] **Ambient mini-player mode** — **NOT BUILT** (verified 2026-08-02: no `mini_player`/PIP/always-on-top playback code exists). Named in the Wave 5 plan; never written. Low-chrome, always-on-top / PIP corner window that expands to fullscreen; the "media in the corner while working ↔ relax fullscreen" continuum (see PRODUCT_VISION.md ambient-companion thesis)
- [ ] **Global playback hotkeys** — **NOT BUILT** (verified 2026-08-02: no global/media-key handler anywhere). Named in the Wave 5 plan; never written. Control play/pause/next/seek without focusing the player window (essential for the corner-companion loop)
- [ ] **Music as a first-class media type** — treat audio/music alongside video in management, queue, and playback (MetaTV is a media *and* music player)
- [ ] **(Stretch) Desktop-embedded video-widget playback** — Linux/KDE: render playback into a desktop-embedded widget that normal windows cover when on top (wallpaper/widget-style ambient playback); platform-specific, experimental
- [x] **"Play Next Episode" button** in history sidebar — SHIPPED v0.19.0 (#228).
- [x] **"Buffer without limit" / start-paused deep cache (download-without-downloading)** — SHIPPED v0.19.0 (#226) for movies & series. The **Cache → Save promotion** half (`--stream-record` retention flag) belongs to the download item below and is NOT built. Original spec: for slow-throughput sources a 30s cache stutters (buffer rides down to 1s→0s); let a stream **keep queuing/caching with no practical limit even while paused** so it pre-loads (ideally the whole VOD) then plays glassy-smooth. *Effectively downloading without downloading* — the data lives in mpv's cache and is **ephemeral (gone when the mpv window closes)**. Extends the existing buffer machinery — `_buffer_profile_args` / `_compose_extra_args` + the `--cache-pause-initial`/`--cache-pause-wait` prebuffer path (reuse, don't reinvent): add an `"unlimited"`/`"deep"` profile **and** a per-stream right-click ("Buffer without limit" / "Start paused & pre-load"). mpv args: `--demuxer-max-bytes=<huge>` + `--cache-secs=<huge>` (raise the forward-cache ceiling — mpv reads ahead *while paused* until the ceiling), **`--cache-on-disk=yes` (REQUIRED** — a multi-GB VOD in RAM breaks the <2GB leanness thesis; disk-back it + purge the cache dir on stop/exit), optional `--pause` to start paused. **VOD-only** (live has no end to pre-load — live-vs-VOD). **Forks:** scope (per-stream right-click [lean] + optional profile / per-provider default, since slow throughput is a *source* property); truly-unlimited vs. **soft cap** [lean] (file size or configurable max-GB / free-disk guard, so a long film can't fill the disk). **Cache → Save promotion (no re-download):** if a deep-cached VOD is later chosen to **save**, don't re-fetch it — persist what's already local. Cleanest mechanism: have deep-cache **write to a real temp file via `--stream-record`** from the start (a playable container — unlike mpv's raw `cache-on-disk` format, which isn't cleanly savable). Then *ephemeral-vs-persistent collapses to a single retention flag*: deep-cache = stream-record to temp, **purge on close**; download = same pull, **keep**; **"Save this"** = flip the temp from purge → keep + register in the library (+ offline badge, note provenance). **One pull, one mechanism (`--stream-record`), retention decided — or changed — at any time**, even after buffering finishes. This is the unifying core of the whole buffer→cache→download→record continuum (deep-cache, download, and live-recording are all the same stream-record-to-disk op differing only in retention + scheduling). Edge case: a *partially* buffered file saves partial (finish the pull, or save-partial-and-note).
- [ ] **Download / save VOD to disk (persistent — sibling of the deep cache above)** — **NOT BUILT** (verified 2026-08-02: no download queue/manager exists). The Wave 5 plan read "deep cache → download → DVR on ONE connection accountant"; only the deep cache (#226) and the connection accountant (#221) shipped. The per-source connection accountant this depends on DOES now exist and is enforced — build on it, don't add a second counter. No download option exists yet. Add **persistently saving a VOD to a local library** (vs. the ephemeral deep-cache above — *same "pull the whole stream" core, the file just stays*). The two are one continuum: buffer-profiles (a little, ephemeral) → deep cache (whole file, ephemeral) → download (whole file, persistent); axes = *amount* + *persistence*. **VOD-only** (downloading live is a separate DVR/record concern). Mechanism options: a direct HTTP GET of the VOD stream URL (Xtream VOD URLs are static files) **reusing the canonical headers/User-Agent** (the player-reliability header work — same UA-gating bug class, *don't drop headers*) with a download queue + progress notifications + resume-partial; or mpv `--stream-record=<file>`. Configurable downloads/library dir; surface downloaded items with an offline-available badge. Neutral framing — standard media-manager offline feature; app is BYO-sources, downloading is the user's choice. **Download queue + connection-aware scheduling (the core constraint):** respects the **per-source connection limit** (`provider_max_connections` — the same one-connection-per-account limit Split Streams is built around). A queued download for source X runs **only when X has a free connection slot** (no active playback on it); **playback preempts downloads** — starting playback on X pauses/stops X's downloads to stay within the limit, and they resume when playback ends. **Per-source, not global** — downloads on source B continue while you watch source A. Plus a global pause toggle (no downloads at all). **Reuse-before-reinvent:** there must be **one per-source connection accountant** that *both* the player (`PlayerManager` instance registry) and the download scheduler consult — do **not** build a parallel connection counter that can disagree with the player; extend the existing Split-Streams connection accounting. Downloads must be **resumable** (HTTP Range) so a preempted download continues rather than restarting — which favors the direct-HTTP-GET mechanism over `--stream-record`.
- [ ] **Live stream recording / DVR (the live sibling of download) — EPG-scheduled, connection-aware** — **NOT BUILT** (verified 2026-08-02: no recording manager / scheduled-recording code). Named in the Wave 5 plan; never written. Record a **live** channel for a time window (you'll miss the game → leave the app up, it records the chosen channel for the chosen window). **EPG-integrated:** schedule a recording straight from an EPG programme — reuse `EpgProgramDB` start/stop times + the watchlist/notification timer infra in `EpgManager` (a "Record" action alongside the watchlist "+"), with **pre/post padding** (start early / end late — live events run over). Manual time-window recording too. Mechanism: mpv `--stream-record=<file>` or a headless ffmpeg capture of the live TS for the window; same downloads/library dir + offline badge. **Connection-aware — third consumer of the one per-source arbiter:** a recording holds a source connection for its whole window, competing with playback + downloads via the **same** `provider_max_connections` accountant (don't build a third counter). **New priority insight — the axis is content *ephemerality/recoverability*, not foreground-vs-background:** a *download* yields freely (VOD is recoverable later), but a *live recording is time-critical — the moment is gone forever* — so a scheduled recording should **reserve** its slot and **warn/block** a conflicting play (*"playing source X now exceeds its connection limit and will kill the scheduled recording"*) rather than silently yielding. So: playback > download (download yields), but a scheduled live recording is **protected** even against playback (or makes the user choose with eyes open). **Limitation:** "leave the app up" needs the GUI process running — a true unattended PVR is the **headless-backend** stretch (PRODUCT_VISION), the eventual upgrade that records without the head up.
- [x] **Stream-retry recovery affordances (2026-06-20 testing pass)** — **S1/S2 SHIPPED v0.18.2 (#220)**, **S3 SHIPPED v0.19.0 (#227)** (failure ledger + graduated states + hidden-count reveal, #233). Original spec below. The background connection checker recovers failed streams, but the recovery UX fell short; tracked S1–S3:
  - **S1 — back-online notification needs a Play button** — when a waited-for stream recovers, the toast should offer a direct **Play** action, not just inform.
  - **S2 — recovered entry should go green & stay, not vanish** — in the stream-retry / connection-available list a recovered stream currently disappears; instead flip its red dot → **green** and keep the row so the user can click to load the stream they were waiting on.
  - **S3 — graduated play-failure state machine → reliability-based fading + dead-content bucket (2026-06-24 testing pass, user-designed).** Right now a failed play (e.g. dead seasonal channels `XMAS NAILED IT! HOLIDAY` / `XMAS MOVIES` / `XMAS HOLIDAY YULE LOG` all returning **HTTP 511**) only surfaces as a transient "Stream Unavailable" toast and is then forgotten — so the user keeps clicking through the same dead streams. **Persist a play-failure ledger** (channel_id, HTTP/error code, timestamp, consecutive-failure count) and graduate a channel through escalating states, each failure tightening it:
    - **State 1 — flagged + queued for recheck (1st failure):** record it and **enqueue a background recheck in the queue we already have** (`stream_retry_manager.py` — the interval responsiveness checker); display stays normal (the user clicked once, we'll quietly verify later).
    - **State 2 — grayed but visible (repeat failure):** on a subsequent failure, **desaturate/grayscale (monotone) the item but keep it in the list** — a clear "not available / not loading" indication, still clickable so the user can manually retry.
    - **State 3 — dead-content bucket (after N attempts):** the channel drops into a behind-the-scenes "dead content" set and is pulled from normal display.
    - **Recovery — opt-in re-check on source refresh:** a **Settings toggle** ("re-check failed/dead channels when a source is refreshed") that, on a source update, re-probes that source's flagged/grayed/dead channels and **restores** any that now load (clear ledger → un-gray → lift out of the dead bucket). The existing background connection checker (S1/S2) also re-promotes a channel that becomes responsive between refreshes.
    - **Reuse, don't reinvent:** the "check again later" step is the **existing** `stream_retry_manager` queue, not a parallel prober; the source-refresh batch re-check rides the existing refresh path. Open knobs (defer): the State-2→3 attempt threshold + decay window; whether the grayed/dead state feeds the data-aware control layer like the other visibility predicates (DR-0007); manual override/unhide. Sibling of S1/S2 — same connection-checker engine, new persistence + a graduated reliability signal on top.

### Source reliability & stream diagnostics

The v0.27.1 batch turned host selection from a lifetime batting average into something that reacts to
what is happening now. Shipped:

- [x] **One chokepoint for URL cycling + outcome recording** — SHIPPED v0.27.1 (#302), `core/url_cycle.py`.
  Seven paths cycled a provider's alternate URLs; five recorded nothing, so a chronically slow host was
  never demoted. All route through `UrlCycler` now. **Found en route:** the previous inline write-back
  never persisted at all — `parse_provider_urls()` returns dicts aliasing the objects already on
  `db_prov.urls`, so mutating in place left SQLAlchemy's history check seeing no change and the
  `commit()` emitted no UPDATE. Every refresh's URL stats were silently discarded.
- [x] **Recency- and latency-aware host ranking** — SHIPPED v0.27.1 (#305). Sort key is
  `(cooldown_tier, -health, median_latency_ms, priority)`; health is an EWMA over recent attempts.
  Previously latency was never measured (a 12s success *raised* a host's score) and a host with 1,000
  successes needed ~1,000 failures to demote. Knobs resolve once at startup into a frozen
  `UrlRankingPolicy` (`core/url_policy.py`) — the `VisibilityScope` pattern, so no low-level object
  holds a `Config`. `UrlCycler.candidates()` logs its decision so the constants can be validated
  against real traffic.
- [x] **A successful failover sticks to the item** — SHIPPED v0.27.1 (#306). The working host is written
  back to the played row instead of being discarded, so a title stops re-paying the stall every play.
- [x] **Diagnostics tests the URL that actually plays** — SHIPPED v0.27.1 (#303). A series channel's
  stored `stream_url` is synthetic (`series_id` + a default `.ts`) and is never streamed, so Diagnose
  reported HTTP 405 on titles that play fine. It now resolves a representative episode.

Remaining:

- [ ] **Episodes never fail over at all** — `launch_player_for_episode` (`gui/main_window_series.py:699`)
  calls plain `validate_stream_url` and never `validate_and_failover_stream_url`, so episode playback
  cannot recover from a dead host the way channel playback can. This is the highest-value remaining
  item in this area: the series/episode case is what surfaced the whole cluster. Route it through the
  same chokepoint (and then through #306's write-back, which keys on `channel_id` and will need an
  episode-grain sibling for `EpisodeDB.stream_url`).
- [ ] **Diagnostics dialog: the raw metrics block is unreadable — demote it to an on-demand popup**
  *(owner UX pass 2026-08-15, spec revised 2026-08-15 after code review)* — the middle section
  carrying Throughput / Bitrate / Baseline / Headroom / Time-to-first-byte / Codec / Resolution
  renders clipped mid-line and is effectively unreadable. **Two corrections to the original note:**
  there is no scroll area anywhere in `diagnostics_dialog.py` — the clipping comes from a word-wrapped
  `QLabel` shown *after* the dialog is already sized, and the dialog never re-sizes to fit it. And the
  block is largely redundant: `_build_summary` (`core/stream_diagnostics.py:504`) already states
  throughput, bitrate, headroom and baseline inline in the verdict sentence directly above it, so only
  time-to-first-byte, codec and resolution are unique to the block (plus `connect_ms`, which the UI
  surfaces nowhere). So the fix is **not** a nicer inline grid: drop the always-on block, add a
  "Technical details…" trigger under the summary, and open the full raw set in a small popup that
  sizes to its own content (which also sidesteps the late-shown-content clipping outright). Confirmed
  working otherwise: the redacted "Testing S03E03: …" URL line and the healthy verdict both render
  correctly.
- [ ] **Validate the ranking constants against real traffic** — *investigated 2026-08-15: the
  constants are not the problem; the latency term is inert.* `url_health_decay` 0.85 /
  `url_cooldown_minutes` 10 / `url_recent_attempts_kept` 20 are chosen defaults. Reading real logs
  showed health decay and cooldown working correctly (values spread 1.00 → 0.00), but **every** host
  reports `latency=0ms`: none of the 15 `UrlCycler.record_success`/`record_failure` call sites passes
  `response_time_ms`, so `median_latency_ms()` returns `0`, and `0` sorts cheapest — collapsing the
  sort key to `(cooldown_tier, -health, 0, priority)`. #305's stated purpose (demoting the host that
  answers in 10-12s but never technically fails) therefore does not happen in the shipped app.
  Latency recording is the prerequisite; only after it lands is there anything real to tune. (Guard
  against the recurring trap: measure the proposed remedy before building more on top of it — this
  item is exactly that guard paying off.)

## Series & Episodes

- [x] **Episodes can be resumed** — SHIPPED v0.27.1 (#304). Resume was gated on `media_type == MOVIE` and `show_episode` never called `set_resume`, so an episode with a saved position offered only Play. The data already existed (`EpisodeDB.watch_progress`, written at three call sites); `start_seconds` is now threaded through the episode launch path, default 0 so existing callers are unchanged.
- [x] **Episode/Season favorites** — SHIPPED v0.17.0 (#204).
- [x] **Episode-grain Watch Queue + favorite in the details pane** *(user 2026-07)* — SHIPPED v0.17.0 (#204). Original spec: when an episode is selected in the series details pane, the "Add to Watch Queue" action currently disappears and there is no per-episode favorite. Add **both at the episode grain** (queue a specific `S##E##`; favorite a specific episode) reusing the existing queue/favorite chokepoints — the actions must operate on the *selected episode*, not silently fall back to the series. (Data model rides the "Episode/Season favorites" item above.)
- [x] **Smart series cache refresh** — SHIPPED v0.17.0 (#203) as `core/series_monitor.py`: recurring background checks with multi-source detection. This is the engine under the series-monitor UX below.
- [ ] **Episode title deduplication** — strip redundant series-name prefix from tree view (configurable via `show_full_episode_titles`)
- [ ] **Cross-source episode completeness tool** — compare season/episode counts across providers per title; extend `scripts/inspect_series.py` with `--live` flag
- [x] **Watch / monitor a series for new episodes — SHIPPED v0.17.0 (#203)**, with click semantics refined in #222. Original spec: let the user "watch" (track) a series so they're alerted when **new episodes appear**. This is the user-facing layer on top of **Smart series cache refresh** (above) — that background check is the engine; this is the tracking + alert UX. Requirements gathered from user:
  - Surfaced in the **watch alerts / watchlist** surface, but **visually distinct** from now-playing / EPG-watchlist items — a different color or its own section — so a *"tracked series has new episodes"* alert reads clearly differently from a *"program is on now"* alert. The two are different kinds of "watchlist."
  - The new-episode flag/alert is **sticky**: it persists until the user either explicitly clears it **or** opens the series (drills in). It must **not** auto-dismiss on a timer like the EPG/now-playing toasts do (`NotificationManager`'s auto-dismiss is wrong here — this is unread-state, not a transient toast).
  - **Cross-source aware:** the same series lives on multiple providers and a new episode may land on one provider before another — so "new episode" detection is per-`(provider, series)` and ties directly to **provider-scoped season keys** (the season-key collision fix) and the **"Most current source"** signal below.
  - Builds on the existing EPG-watchlist prototype + the series cache-refresh mechanism. See memory `project_watchlist_roadmap` (movie/series appearance + new-episode alerts already flagged high-priority, not yet built).
- [x] **Persist alert matches into an "Alerts Matched" Watch-Queue section** — SHIPPED v0.17.0 (#205), click semantics in #215. Original spec: VOD/series monitor matches (e.g. "Masters of the Universe" appears, a tracked series gains a new episode) currently only **toast** and are easy to miss. Land each match into a persistent **"Alerts Matched"** section of the Watch Queue so the user can review/act later, not only in the moment. Sticky (clears on open/act, not on a timer), visually distinct per the two-kinds-of-watchlist rule above.
- [x] **Alerts management panel** — SHIPPED v0.17.0 (#206) as "Manage Watch Alerts", including the recoverable-remove (strikethrough + Undo) requirement. Original spec: one panel to manage watch-for keyword alerts **and** monitored series: a monitored-series section, per-rule enable/clear, and **recoverable remove** — strikethrough + an **Undo** in the delete's spot (scope = both keyword alerts and monitored series) so a mis-click is reversible (mirror-not-cage). Note: an alert rule is the same facet/keyword query as a **recipe** — see the parked *Recommendations ↔ Recipes unification* (`project_recommendations_recipes_unification`); revisit whether alerts management folds into the recipe surface.
- [ ] **"Most current source" signal for a series** — the *same* series often appears on multiple providers (already grouped by the cross-source dedup fingerprint and surfaced as version chips in the details pane), but one provider's catalog is often more up to date than another's (more seasons, newer episodes). Today the user has to drill into each source manually to tell which is current. Idea: surface a lightweight "most current" hint on the **series** details-pane version chips (movies have no episode-completeness axis — series-only). Assessment of cost: the raw signal is cheap **once each source has been drilled into** — compare the already-stored per-`(provider, series)` `SeasonDB`/`EpisodeDB` rows by max `season_number`, total `episode_count`, and newest episode `raw_data.info` `added`/air date; no extra network. The *expensive* part is comparing sources the user **hasn't** drilled into yet — that needs an on-demand `get_series_info` call per provider-version (N API calls), so the cheap MVP only compares sources already loaded. **Prerequisite:** provider-scoped season keys (the season-key collision fix) — without it two sources' seasons clobber each other in `SeasonDB`, so there's nothing to compare. **Likely superseded by TMDb:** once TMDb is the canonical episode list (source of truth), "most current" becomes "which provider's episode set best matches the canonical TMDb list," a cleaner definition than the interim max-count/recency heuristic. Keep this low-complexity until then. **Refined by real data (2026-06-19):** the comparison is **not only cross-provider — it's cross-version within a single provider**. One provider commonly lists the same show several times in different language/quality categories (the version chips), each a separate series entry with a *different* season set. Real example, all on one source: `EN - South Park` = 28 seasons (1–28), `EN - South Park 4K` = 25 (1–25), `ES - South Park` = 20 **with a gap (5–9 missing)**. So "most complete" must weigh **contiguity/gaps**, not just max-season-count — the ES version reaches season 25 but is missing the middle, arguably worse than a complete 25.
- [ ] **Series data-anomaly transparency (don't let data-accurate gaps confuse users)** — when a provider's catalog for a series is sparse, the UI today renders it faithfully but confusingly. Two distinct anomalies, both *data-accurate*, both confusing:
  1. **Non-contiguous season numbers.** For providers that return `seasons: []` + episodes keyed by season number, we synthesize one season per numeric key present and preserve the provider's real numbering. If the provider's data skips seasons (ES South Park has no 5–9), the tree jumps "Season 4 → Season 10" and the toast reads "Loaded 20 seasons" while the list shows *Season 25*. Count (20) and numbers (max 25) are both correct; the gap is real provider data (confirmed: the **episodes** table also has nothing for 5–9, and both seasons and episodes derive from the same response dict). **De-confuse (shipped):** the tree now renders a muted inline note when seasons are non-contiguous — `Seasons N–M not provided by this source` (`main_window_series.py`, `tests/test_series_anomaly_transparency.py`) — so the jump is explained, not mysterious. *(Remaining sub-items below are still open.)*
  2. **Same show, different versions, different completeness** — see "Most current source" above; surface per-version season counts + a "most complete" marker on the version chips.
  - **Definitive diagnosis tool (the pin-down):** stored data can't distinguish "provider genuinely lacks 5–9" from a parser edge case (e.g. the provider sent seasons 5–9 under *non-numeric* keys like "Temporada 5", which `s.isdigit()` would silently drop — no synthetic season → those episodes never stored, invisible in the DB). The decisive check is the **raw `get_series_info` response keys**. Add the already-planned `--live` flag to `scripts/inspect_series.py` to re-fetch and dump the raw season/episode key structure for a `series_id`.
  - **Parser robustness (make anomalies self-diagnosing):** the synthetic-season path should **log a clear warning listing any episode-group keys it can't map to a numeric season** (and when seasons metadata is empty), so silent drops become visible/diagnosable instead of mysterious later. Small, defensive; turns "why is this series weird" into a grep.

## Discovery & Recommendations

- [x] **Channel-level deduplication** — SHIPPED v0.21.0 (#240) as an opt-in "collapse quality/language versions in the channel list".
- [ ] **Related content suggestions** — in details pane, beyond current Similar Titles lightbox
- [ ] **Finish the Similar Titles lightbox — surface "why similar" per title.** The #327 redesign delivered the see-and-pick core: the lightbox now shows a **scrollable contextual strip of the similar set** (poster + rating/runtime/type + source) with a ⤢ dive-in on every row, so you no longer cycle blindly through prev/next arrows (`similar_lightbox.py`, `similar_lightbox_card.py`). **Remaining:** surface **why each is similar** — the link reason (a shared *title token* for Similar Titles, or shared genre/cast/director for the metadata "Similar Content" sibling), tying to the "why was this recommended?" explainer. Broader vector: surface "more like this" in more places (inline details, **post-playback "similar next"**, History/Recent, "because you watched X"). It renders the same `discover_card` + adjacency plumbing as Discover (DR-0002). **Cleanup when touched:** audit the redesigned `similar_lightbox.py` for any remaining inline color literals (tokenize to `theme.COLOR_*`, CLAUDE.md no-inline-color rule).
- [ ] **Adjacency navigation breadcrumb — the deep-rabbit-hole trail.** *(LARGELY SHIPPED v0.14.1: the **Explore trail-map** (#336) — a cascading-columns adjacency browser opened from the lightbox, seeded with the walked trail — realizes "see the whole trail", with path-aware **breadcrumb highlighting** (#338, part E); an in-lightbox one-line breadcrumb remains the lighter inline variant.)* Non-destructive adjacency is now complete: the #327 redesign made *in-lightbox* exploration non-destructive (**Back** with Backspace, **Esc** returns to your anchor), and a details-pane Similar-title click now **opens the lightbox by default** instead of replacing the pane — the per-row ⤢ button was removed (the row itself is the trigger; right-click still commits to the full details pane). **Remaining:** a *deep* rabbit hole (A→B→C→D inside the overlay) still benefits from seeing the whole trail — add a **subtle in-lightbox breadcrumb** (*Origin › A › B*), **not a button**, which makes the thread legible (see "Two contextual discovery sections" below and DR-0003 — a weak "just a shared word" hop is the feature working, not a defect). Keep on the canonical details/lightbox surface (DR-0002).
- [ ] **Explore trail-map columns: blend in preference-scored "more like this", not just title matching** — **NOT BUILT** (verified 2026-08-02: `explore_view.py` populates purely through the `get_similar_channels` title-token adjacency chokepoint and has ZERO `preference_engine` references). This was recorded as part of the "spec-locked" Wave 7 build list and never written — a claim, not a delivery. The cascading Explore columns (#336, opened from the History "Explore →" link + the lightbox) currently populate each column via raw **title-token** similarity only. Extend each column to *also* surface **preference-engine-scored** matches for the focused item — genre/director/cast/keyword TF-IDF, the same scoring **Recommendations** uses (`preference_engine`) — so a column blends the crude cross-genre title-hops with essence-based neighbors. Turns Explore into a per-item recommendation lens, not just a same-title-variant browser. Ties to the crude-vs-essence split below (DR-0003) and reuses the existing scorer. *(owner steer 2026-07-31)*
- [x] **Give Favorites, Watch Queue, and Recommended their own "Explore" cascading-columns views (next release)** *(owner steer 2026-07-31)* — **SHIPPED v0.15.0:** the Full Watch-History view was generalized into one parameterized `ExploreView` (`metatv/gui/explore_view.py`) driven by an `ExploreSource` registry, and **Favorites**, **Watch Queue** and **Recommended** each grew the shared **Explore →** header link (`CollapsibleSection._add_explore_link`, opted into via `EXPLORE_KEY`). One component, four entry points — column 0 is seeded from that section's own contents (favorites in rail order, the queue in the user's `position` order, the rail's own `preference_engine` result), cascading outward via the existing scoped adjacency plumbing. Favorites/Queue/History stay record views (DR-0007 exemption); Recommended keeps the hidden-provider gate and does **not** re-record impressions. **Remaining:** blend preference-scored neighbours into the drilled columns (item above); pairs with the "Reusable Discovery-shelf collection views" item in UI/UX.
- [ ] **Two contextual discovery sections in the details pane: keep Similar Titles *crude*, add a *Similar Content* (metadata) sibling** — **NOT BUILT** (verified 2026-08-02: no `similar_content`/metadata-adjacency code exists). Recorded as part of the "spec-locked" Wave 7 build list and never written. *(see DESIGN_RATIONALE DR-0003; user steer 2026-06-20.)* The details pane should carry **two distinct, parallel adjacency lenses anchored to the current item**, which return *completely different* result sets: **Similar Titles** = raw **title-string** linkage (lateral / explore / **anti-filter-bubble** — its crudeness jumps *across* genres to surface totally different things sharing a thread; real use: it has surfaced content the user would *never* have browsed to find; do **not** homogenize it) and a new **Similar Content** = **metadata** linkage (genre/cast/director/keywords + `preference_engine` TF-IDF — "things like THIS in essence"). Both are *contextual/micro* (anchored to the item), distinct from **Recommendations** (global + personalized to *your* taste profile). The value is partly the **contrast** (same anchor, crude-vs-essence neighbors). Canonical `tmdb_id`/`imdb_id` work serves Similar Content + Recommendations + dedup (don't false-merge productions → the South-Park bug) — **not** Similar Titles, which stays raw.
- [x] **Collections as Discover shelves** — SHIPPED v0.24.0 (#256/PR #399): `get_all_collections()`/`get_by_collection()` in `discovery_engine.py` surface the ingestion-computed `detected_collection` (Apple+ Kids, Hindu Subs, …) as shelves, mirroring the genre-shelf pattern — same scoping kwargs, same `content_key` dedup, hidden providers excluded, ≥2 members (`MIN_COLLECTION_SHELF_MEMBERS`), deterministic ordering, pure-lazy card loading preserved.
- [ ] **Trending content** — requires external data feed
- [~] **Canonical content IDs (TMDb/IMDb)** — PARTLY SHIPPED, and this line was stale: the canonical key does **not** depend on an external TMDb provider. `content_key` has been tmdb-first since #317 (`tmdb:{id}|{media_type}`) using the id the provider's own payload carries, so cross-source dedup already keys on TMDb ids with no API key. What remains is IMDb ids and using external-API ids for rows whose provider supplies none. Note the stopgap below applies only to the Phase-2 runtime fingerprint (recommendations/Similar), not to stored `content_key`: current `(norm_title, media_type, year, director)` fingerprint is a stopgap with known false-split risks (see CLAUDE.md § Content dedup)
- [x] **Copies of the same film find each other again** — SHIPPED v0.26.0 (#284). A film could split into several separate identities, so its own copies did not recognise each other and "Other versions" read empty or incomplete ("The Lobster"). Root cause was two competing definitions of "same title" — one identity is computed at ingestion and read everywhere, per `docs/CONTENT_IDENTITY.md`.
- [ ] **Dedup transparency toggle** — advanced/debug setting to bypass recommendation dedup and see raw scored candidates; paired with a "why was this recommended?" explainer; useful for diagnosing cases where the heuristics make bad assumptions
- [x] **Recommendation-scoring settings panel — user-tunable dials** — SHIPPED v0.16.0 (#195), with the damped-proportional movie/series mix + Automatic/% override in #194. Original spec: expose the `preference_engine` scoring knobs in a settings panel the user can override/tweak: attribute weights (genre vs director vs cast vs keyword), the **actor corroboration gate** (`ACTOR_MIN_SUPPORT` / `ACTOR_WEIGHT` — how many liked titles before a performer counts, and how much), the **within-generation people-diversity decay** (`PEOPLE_DIVERSITY_DECAY` — how hard a repeated performer/director is pushed down so other content surfaces), impression-decay rate, the like-cap, and the **movie/series balance**. **Movie/series balance — make it proportional to engagement (owner steer 2026-07-31):** #350 ships a hard 50/50 round-robin (`balance_media_types`); the *right* default is to mirror how much the user actually engages with each type, **dampened** so the minority still shows — square-root damping of the engagement counts matches the owner's target (rate 100 movies : 15 series → √100 : √15 ≈ 10 : 3.9 → ~72% : 28% → **7 movie / 3 series** in a 10-slot list; a 50/50 or 100/0 engagement stays 50/50 or all-one-type). Compute the share from the same positive signals used elsewhere (liked + favorited + queued + watched, by `media_type`). **Surface the ratio in the Recommendations chip/view** — an "**Automatic**" label (the damped-proportional default) that the user can override with a **slider for % movies : series**, so the mix is both visible and steerable. Ship sensible defaults that "just produce a good stream of content the user finds valuable" — the panel is for people who want to steer, not a requirement. Guiding lesson that motivated it: raw scoring was **volume-biased** (richer-metadata movies out-summed thinner-metadata series, and a single performer could dominate); the fix normalized per-field means + gated actors + balanced media types (this release), but the *right* weights are a matter of taste, so give the user the dials. Pairs with the "why was this recommended?" explainer above and the AI taste-profile item below.
- [ ] **AI-powered personalization from user categories** — once an LLM provider is wired (Claude API / local), use user category names + mood signals + watch history to generate natural-language taste profiles ("you prefer slow-burn character dramas, avoid reality TV") that feed the recommendation engine; category mood weights become the training signal
- [ ] **User category genre/type contextualization** — after creation, the recommendation dashboard can surface "Your 'Quranic Recitations' category is tagged Religious/Music — adjust how it influences recommendations?"; the engine infers genre from existing channel metadata, user just confirms or overrides; intentionally deferred from creation dialog to reduce friction
- [ ] **Discovery shelves from user categories** — extend user-category shelves with "More like this category" auto-generated sub-shelves; if user created "Korean Drama" with Like mood, auto-generate a "More Korean Drama" shelf from unassigned Korean channels matching genre overlap
- [ ] **App-behaviors setting: background pre-warm of collapsed Discover shelves** — **NOT BUILT** (verified 2026-08-02: no pre-warm/preload code). Recorded as part of the "spec-locked" Wave 7 build list and never written. Discover now loads **pure lazy** (collapsed shelves are header-only strips; cards fetched on expand). Add an opt-in setting — on a new **"App Behaviors"** settings tab (app-wide behavior toggles) — that, when enabled, quietly background-fetches the collapsed shelves' cards after the visible ones paint, so expanding a strip is instant. Off by default (keeps cold start snappy); the engine already supports per-shelf fetch, so this is just a low-priority background sweep + the toggle.
- [ ] **History as a context engine + self-reflection surface (the twin of Recommendations)** — **split History by register** (see UI/UX "Sidebar register split" and DESIGN_RATIONALE DR-0001): keep a lightweight **Recent / resume strip in the rail** (forward instrument — last N played, recency-ordered, one-click to jump back in: resume-after-crash, re-find a browsed-past item, **re-join an ongoing live event** like the World Cup; resume semantics differ — VOD resumes at position, live re-tunes to latest) **and graduate the deep History archive to a first-class main-area view.** *(SHIPPED v0.14.1: the **Full Watch-History view** (#337) graduates History to a main-area view, reusing the Explore trail-map component (seed = watch history, with watch-count / last-watched); watch-count/temporal-affinity stats + the taste-mirror framing remain. NEXT-RELEASE fix: it's embedded in the cramped middle panel → make it auto-collapse the sidebar+details for full room. See project_next_release_shakeout.)* History is the *evidence* end of the recommendation loop while Recommended is the *inference* end; today the evidence is a flat list. Flesh the archive out: watch counts (how many times, and crucially *when* — time-of-day / day-of-week affinity), the rating shown inline (liked / not interested), filterable, with stats and **temporal-context modeling** ("Friday-night sci-fi"; comfort late / explore early) that feeds the engine's comfort↔explore phase detection. **Dual purpose:** feeds the engine *and* hands the user a **taste mirror** for self-reflection (navigate your own likes outside the app, not a black box). **Guardrail (design tenet — PRODUCT_VISION #8):** *surface* patterns to the user (mirror), never silently *pre-filter* their choices into a self-fulfilling prophecy (cage). Excluding specific categories/tags from history context is future tag-system work.
- [ ] **Watch Queue aging / organization** — the queue gets unruly: items added on different days get "lost in the middle," so users fall back on History as a loose-capture net (see History split, above). Needs recency/date-added grouping, reordering, and an age-out/archive affordance for stale entries — and consider whether a lighter "interesting, maybe later" capture is missing between the *committed* queue and the *ephemeral* History recency strip (don't add a third bucket reflexively — the Recent strip may already cover the "I saw it, let me get back to it" case). **Live ≠ VOD in the queue:** adding a live channel sends it to the *bottom* of a positional list (scroll all the way down) — wrong affordance, because live is *now/recency*-oriented, not a planned position. The queue reads as a movies/series construct; live "get back to it" belongs in the **Recent strip** and/or a dedicated **live-follow pin** ("channels I keep returning to"), not the VOD queue. (Connects to the media-type split surfacing across History/Queue/Recent — see DESIGN_RATIONALE DR-0001 Refined note.)
- [x] **Discover view polish (2026-06-20 testing pass) — SHIPPED** (verified 2026-08-02: D1 deterministic card sizing + D3 stable expand button in #92, D2 deferred collapsed-strip build + D4 collapse-to-top in #93, D5 genre unification via stored `detected_genres`, D6 zoom slider in #94; tests: test_discover_layout_bugs / test_discover_d2_d4 / test_discover_genre_unify / test_discover_zoom) — concrete issues found in real use; shipping as small PRs, tracked D1–D6:
  - **D1 — cards render "smooshed" on expand-from-collapsed** *(in progress — PR)* — fixed-size cards collapse to slivers on subsequently lazy-expanded shelves: the lazy `set_cards()` path sizes the inner row via an ill-timed `sizeHint()`, while the eager build uses a settled `adjustSize()`. Fix: size the row **deterministically** from the fixed card dims via one shared helper both build paths call (`discover_shelf.py`).
  - **D2 — collapsed-shelf counts cause scroll stutter** — collapsed strips already skip the card query, but their *count* is computed eagerly. Defer counts to an idle/afterthought load so expanded shelves stay smooth.
  - **D3 — hide button steals the expand button's hover slot** *(in progress — PR)* — on a collapsed strip the expand `>` is far-right when idle, but hover reveals the hide `⊘` to its right, flipping the click target expand→hide (mis-clicks). Make **expand always rightmost & positionally stable**; pin/hide reveal to its left (`discover_shelf.py` header order).
  - **D4 — re-collapsed shelves land at the bottom of the collapsed zone** — add a `discover_collapse_to_top` preference (default top) so a just-collapsed shelf returns to the **top**, not the bottom.
  - **D5 — shelf genres not unified across languages** — Drama / Drame / Dramma / دراما surface as separate shelves. The canonicalizer **already exists** (`normalize_genre()` / `_GENRE_NORM` in `repositories/channel.py`, FR/DE/ES/IT/NL/AR); it just isn't applied in the Discover shelf path. Wire it into `discovery_engine` (`_primary_genre` / `get_all_genres` / `get_by_genre`) so aliases collapse into one shelf; grow the map as gaps show. **This is the pilot for the tag/attribute overhaul (DR-0005) — the first canonicalization rule.**
  - **D6 — Discover zoom slider** — a scale factor over the card poster / `_CARD_W` / `_POSTER_H` / font constants, exposed as a slider in the Discover header and persisted, so users on large/HiDPI displays (or wanting more/less density) can resize posters + text. Builds on D1's deterministic sizing.

## UI / UX

- [ ] **Sidebar register split + History/Recent + Sources status strip** — the left rail is over-saturated because it stacks three *registers* of information in one column (see DESIGN_RATIONALE DR-0001): **live/prospective** (Alerts, Watch Queue, Recommended — change on their own), **curated/retrospective** (Favorites, the History *archive* — change only when the user acts), and **system status** (Sources — online/active + the global show/hide filter). Reorganize by that axis: the **rail is a launcher/index into deeper views, not a content container** (root thesis — depth lives in the windshield views; only in-the-moment/forward items keep a rail face). Forward-instruments stay as the default rail; **split History** into a lightweight **Recent/resume strip** that stays in the rail (forward) and a **deep History archive** that graduates to a main-area view (see "History as a context engine"); **Favorites graduates to a windshield view** (Discovery-shelf collection) rather than a privileged rail section — real use: sidebar Favorites goes unused; **Sources** becomes an always-visible **collapsed status strip** above Settings (one-line summary → expand for per-source toggles + filter), never a tab. **Every new sidebar section must declare its register.** A recurring **live-vs-VOD** distinction runs through this (Recent re-tunes live vs. resumes VOD; the queue is a VOD construct). Open: live-follow as its own surface vs. the Recent strip; sequencing vs. the series-monitor feature.
- [ ] **Reusable Discovery-shelf collection views (full Queue / History / Favorites views)** — generalize the `discover_shelf` / `discover_card` / flow-layout widgets into a **reusable collection-browse surface** (not Discovery-specific; reuse-before-reinvent). Concretely: a **full Watch Queue view** in the Discovery shelf style (posters organized by category/tag) reached by a new **Queue chip** on the bottom row — the windshield "face" of the rail's compact queue (see DESIGN_RATIONALE DR-0001 "Emerging pattern"). The same surface backs the History archive view and possibly Favorites. **Preserve order where it matters:** the VOD queue needs an **Up-Next** ordered lane alongside the category shelves so grouping doesn't bury "what's next"; live-follow content isn't queued (live-vs-VOD). One shelf presentation layer, many collections.
- [ ] **UI vocabulary standard** — note the settled term is **"Global Exclusions"**, never "Global Filter(s)". Define one canonical term per action across all surfaces: "Exclude" for filter/suppression (panel or global), "Hide" for per-channel hiding, retire "Block" as a synonym; document in UI_UX_GUIDELINES.md and enforce in new UI code
- [x] **"Search this title" context menu action** — SHIPPED v0.16.0 (#200) via the `channel_menu.py` registry (`search_title` action), sharing one title definition with Copy title so the two can never disagree.
- [x] **"Copy title to clipboard" context menu action** — SHIPPED v0.16.0 (#200) as the `copy_title` action in the `channel_menu.py` registry.
- [~] **Unified filter panel across views** — a shared `FilterPanel` exists and is used by the main channel list; EPG, Discover and Recommended still carry their own controls, so the unification itself is open. **Blocked-adjacent:** the deeper problem is four parallel *filter engines* (`_apply_channel_filters`, `discovery_engine`, `preference_engine`, `tag.py._scope_to_visible_channels`) — being unified in v0.24.0 behind `core/channel_visibility.py`. Do the UI unification after that lands, not before. Original spec: EPG, Discover, and Recommended each have their own filter controls; goal is a single FilterPanel (or shared filter state) across all views; migrate EPG sports filter bar, discover chips, recommendations filter to the same pattern; deprecate the legacy "quick filter" bar where it still appears
- [ ] **Uncategorized prefix audit** — classify GO, CITY, V+, ONE, SU, VD, SKR, BEE, TY, RD, RG, RX, PLAYER, TF, CON, LSV, TEN, TK, BLUE, GEN, NIC, FZ, LUX, PN, TGK, CRB, EST into known groups; user is actively building the mapping
- [x] **Settings page architecture** — SHIPPED v0.20.0 (#234): Settings redesigned as a three-panel layout.
- [x] **A facet may reject a value, never an absence** — SHIPPED v0.27.0 (#299/#300). Unticking one box in a filter section did not remove that one thing — it removed everything the app had never tagged on that whole facet, so untick a single subtitle language and every untagged title vanished with it. Absence is now its own explicit, separately-controlled row: each section carries an "Untagged — N" entry at the bottom, so the filter can say what it cannot describe instead of silently discarding it.
- [ ] **Filter system improvements** — search within excluded results for 50k+ filtered datasets; provider-level filtering when multiple providers active
- [x] **Name-based restricted-content detection → isolate from general surfaces** — SHIPPED v0.20.0 (#238): the restricted-content filter now catches name-flagged channels, not just provider-flagged ones. The `is_adult`/`filter_adult_mode`/`build_adult_filter` → neutral-term rename remains a tracked cleanup. Original spec: the restricted-content hide/only filter keyed off the provider's `is_adult` API flag only. Channels named with restricted prefixes (XXX / ADULT / X — grouped under the "Adult" prefix-filter category) are NOT caught when the provider doesn't flag them, so they **leak into general Discover shelves** (e.g. an `X`-prefixed item showing up in "Top Rated Movies"). Detect restricted content from the prefix/name at ingestion (set the flag) so the hide filter isolates it everywhere — Discover shelves, recommendations, general browse. *Display grouping already exists; this is the filtering half.* **Naming convention (user steer 2026-06-19):** use a **neutral, abstract term in code** — `restricted` / `isolated` (not "adult"); reserve the word "Adult" for the **UI label** only. Applies to the eventual rename of `is_adult` / `filter_adult_mode` / `build_adult_filter` too (a tracked cleanup, not done yet).
- [ ] **User-side category management — DEFERRED to the tag system.** Right-click "Add to Category" / "Remove from category" on a channel, and a "manage a category's contents" view, are intentionally **not being built now**: the whole category concept is going to be rehashed by the faceted/typed-**tag** model (see "Faceted/typed-tag model"), so investing in the current single-assignment category UX would be throwaway work. Today the only path is right-click → "Category: … (change…)" (CategoryPickerDialog) to re-assign one channel. **What IS still worth doing before tags:** the *source-data → category* **parsing/ingestion** side (how provider categories/prefixes map to groups) — that mapping is the foundation the tag system will build on. The *user-facing* category-editing surface waits for tags.
- [ ] **User-defined prefix groups** — UI to assign "Other" prefixes to existing groups or new custom groups (e.g. promote "ARAB" → Arabic, or create "My Sports" = [ESPN, DAZN]); backed by `user_prefix_overrides` config already in place; "Reset to defaults" clears overrides and reverts all prefixes to built-in group mappings
- [ ] **"Copy filters from…" across views** — apply a Tier 1 filter from one view (Search/Discover/EPG) to another; small dropdown on each filter bar
- [ ] **"Promote to global exclusion"** — convert a dialed-in Tier 1 view filter into a Global Exclusion (requires inversion: everything NOT selected becomes excluded); useful when you've found a good filter config and want to make it permanent
- [~] **Hidden-content visibility & recovery surface (mirror-not-cage)** — PARTIALLY SHIPPED: hidden **counts + reveal** landed for global exclusions and for dead/failed streams (#233, #245), and standalone region/locale tokens now render in the Exclusions dialog (#231). **The Hidden Management VIEW itself is NOT BUILT** (verified 2026-08-02: no hidden-management surface exists) — the review-and-recover destination, the right-click entry point from the Search "Hidden" toggle, and the per-variant "exactly HOW is this filtered" tooltip all remain. Original spec: today the app can cage content with **no way to see or recover it**: a search can return 0 results with no "N filtered/hidden" warning, and the Global Exclusions dialog doesn't render standalone region/locale tokens (an `FR` in `global_filter_excluded_prefixes` maps to no category group → reads as "no filter" while still filtering). Build a **Hidden Management view** that surfaces "**#### channels completely hidden with no way to view or recover them**" (completely-hidden = excluded by the union of global exclusions, hidden categories, removed/inactive/expired sources, adult-gate, with **no visible variant**) and lets the user review + recover. Entry points: **right-click the "Hidden" toggle in the Search bar → open the Hidden Management view**; the search empty-state shows an "N filtered/hidden — review" affordance (extends the #238 hidden-count). The Global Exclusions dialog must also surface **every** active exclusion token (incl. region/locale codes) so nothing is invisible. **Filtered-variant tooltip:** hovering a chip under "Filtered variants" must explain **exactly HOW** it is filtered (which axis + token), with enough clarity that the user can undo it from the management interface. (Per-variant unblock lever fixed in #284.)
- [ ] **Faceted/typed-tag model for channel metadata — FUTURE ARCHITECTURE (the data-organization rethink).** The prefix/code taxonomy currently forces each code into **one** bucket across three filter axes (locale / platform / quality), but real codes are **multi-type facets**: a single channel legitimately carries several typed tags at once. The cracks are already visible — `SC` is *Subtitles: Scandinavian* on foreign original-audio content (parked in **Platform**), `EAR` is *Subtitles: Arabic* (Platform), `Adult` is a *Genre/content-category* (parked in the **Language/locale** tier, with a "not a locale" comment admitting it). The user's articulated model (2026-06-19): category **types** are like **Language, Platform, Genre, Region, Quality, (Subtitles)**, and a source item can hold **multiple** tags across those types. Direction: rethink whether these are single-assignment "categories" or multi-assignment **tags/facets** — a channel → a *set of typed tags*; filtering becomes facet selection within and across types (the union/restrict semantics of the current six axes become per-type tag selectors). Generalizes the existing **"Channel sub-attributes / session type tags"** item (the `channel_tags` JSON column) and the six-axis model in `docs/FILTERING_DESIGN.md`. Touches ingestion (tag extraction at parse time), schema (`channel_tags`), and the filter UI. **Not now** — the `SC`/`Adult` mis-bucketing is the early symptom; until the model is reworked, leave `Adult` parked and `SC` in the platform/library tier (its `config.py` comment is stale: it's a Scandinavian-subtitle library, twin of `EAR`, not "origin TBD / English-Turkish-Indian"). Reconcile the `channel_name_utils.py` "Scandinavian" label vs the `config.py` platform framing as part of this.
- [ ] **Grid view** for channel list — **NOT BUILT** (verified 2026-08-02: `ChannelListView` is a plain `QListView`, never set to `IconMode`; only Discover has a card grid). Named in the Wave 6 plan; never written.
- [ ] **Keyboard shortcuts** — **NOT BUILT** (verified 2026-08-02: the ONLY shortcut in the app is `Ctrl+,` for Settings at `main_window.py:822`; no `QShortcut` is registered anywhere in `gui/`). Named in the Wave 6 plan; never written. Ctrl+F focus search, arrow key nav, Esc clear search
- [~] **Dark mode / theme selection** — palette LAYER shipped v0.21.0 (#239: Midnight/Graphite/Daylight) and #251 claimed completion, but the owner's 2026-08-02 UX pass proves the APPLICATION layer is very incomplete: bottom nav bar and status bar render white in a dark theme, details-pane section headers render near-black on near-black, poster placeholder is a light-theme box. Root cause is not stray literals (`test_no_stray_color_literals.py` is correctly green) — it is widgets built with NO stylesheet inheriting Qt's default light palette (`details_sections.py:1250`/`:1322`, `main_window.py:809`), because `MainWindow.refresh_theme()` is a hand-maintained enumeration sweep that cannot see an absence. **Application-layer floor SHIPPED v0.24.0 (#253/PR #401):** `theme.qt_palette()` builds a `QPalette` from the active tokens and `apply_theme()` pushes it onto the whole `QApplication`, so a widget with no stylesheet inherits themed colours instead of Qt's built-in light default — no enumeration required. It also fixed a latent bug: a non-default saved theme was never applied at cold launch at all, only after a Settings round-trip. **Six restart-only views SHIPPED v0.24.0 (#261):** Discover, Recipe, EPG, Preferences/Recommended, Provider editor and Sources manager each gained their own `refresh_theme()`, swept by name from `MainWindow.refresh_theme()`. **Selection contrast SHIPPED v0.24.0 (#265):** the QPalette highlight took its foreground from the on-background text ramp, which put near-black on Daylight's navy accent (~1.2:1) and white on the dark palettes' light-blue accent (~2:1); a dedicated per-palette `COLOR_ON_ACCENT` token now clears 4.5:1 in all three, guarded by a contrast test that reads the roles back off the real `QPalette`. **Live theme switching SHIPPED v0.26.0 (#286):** the restart-only residue was fixed by a palette-diff rewrite, not by extending the sweep — `theme.style(w, "ROLE")` registers each widget weakly so `apply_theme()` re-applies it, replacing the hand-maintained `refresh_theme()` enumeration that could never see a widget nobody remembered to add (#253/#261 both "completed" it and both left it broken). A drift-guard test now fails the suite on any raw `setStyleSheet(theme.X)`. **Contrast SHIPPED v0.27.0 (#296, #298):** the primary view chips (Search/EPG/Recommended/Discover/Recipe) were unreadable in both states on both dark themes, and Graphite was barely distinguishable from Midnight; #298 then measured *every* foreground/background pair the stylesheets set and repaired nine unreadable control states — found by measuring rather than by looking, which is the reusable part.
- [ ] **Channel sub-attributes / session type tags** — bracket suffixes like `[FP1]`, `[RACE]`, `[SPRINT]`, `[Prelims]`, `[Main Card]`, `[EVENT ONLY]` encode valuable sub-category data (Formula 1 session type; UFC/combat sports segment). No DB field exists today to store these — they're left in the bare channel title for now. Needs a `channel_tags` or `session_type` JSON column so sessions can be filtered ("show me only F1 Race rounds, not practice"). Related: `[WEST]`/`[EAST]` US regional variants would also benefit from a sub-region field.
- [x] **Panel layout menu + panels stop shrinking** — SHIPPED v0.26.0 (#288): show/hide sidebar, details pane and filter panel without hunting for a splitter handle; each remembers its width.
- [x] **Find a Discover shelf by name** — SHIPPED v0.26.0 (#287): a large library produces ~1,900 shelves, which made scrolling to one impractical.
- [x] **Watch Queue search + ordering** — SHIPPED v0.26.0 (#291 filter box, #289 newest-first): "Never Watched" listed oldest-first forever, so a months-old queue permanently buried what you just added.
- [x] **Recommended keeps its scroll position** — SHIPPED v0.26.0 (#290): refreshing or expanding versions bounced you back to the top.
- [x] **Sidebar header repetition** — SHIPPED v0.26.0 (#293): four "Explore →" links down one narrow column stopped reading as navigation.
- [x] **Results row emphasis hierarchy** — SHIPPED v0.27.0 (#295): a row carried seven competing boxed treatments at once with nothing dominant; rebuilt on three emphasis tiers so the title is the loudest thing.
- [x] **"No poster available" centred** — SHIPPED v0.27.0 (#297).
- [ ] **Episode history tracking fix** — debug logging to trace why parent channel lookup sometimes fails for history updates
- [x] **Restore ratings display in details pane** — SHIPPED v0.16.0 (#199).
- [x] **Details pane — move "Source:" beneath title/year** — SHIPPED v0.16.0 (#198). Original spec: relocate the Source field (currently below the metadata block) to the right side of the title row, inline with or directly beneath the title + year line; keeps the primary content area cleaner and puts provenance info near the header where it's most useful
- [ ] **Launch-time feedback prompts** — while channels load at startup (5-10s), show "You watched [X] — what did you think?" prompts for recently-watched content with no rating; feeds the recommendation engine quickly; opt-in ("Ask me about content I watch"), explain data stays local; dismissable and rate-limited so it doesn't become annoying
- [ ] **Recommendation dashboard — category mood editor** — show all user categories with their current mood, channel count, and inferred genre; let user adjust mood in bulk without re-opening CategoryPickerDialog; "Why is this recommended?" explainer links back to category mood contributions

## Code Health / Refactor

The big refactor work is **done** — Bands 1–8 (2026-06-01 → 06-14; details in git history)
delivered the structural fixes (`session_scope`, `closeEvent` registry, `JSONEncoded`, `icons.py`,
EPG conversion boundary), `theme.py` token migration, `main_window.py` decomposition into mixins,
the `_run_query` async-read seam + repository DTOs, and the `BackgroundRefreshMixin` sidebar pattern.
The unified channel-menu registry (2026-06-19) closed the long-standing context-menu duplication.
What remains is small, not a "massive refactor" — see the **[2026-06-19 audit](docs/AUDIT_2026-06-19.md)**
for the full findings + the **Band 10** remediation plan (P1: `expunge`→DTO, render-parse cleanup;
P2: file splits, the `font-size`→`FONT_*` rule/cleanup):

- [x] **Band 9 — DONE** (folded into Band 10): B9-1 `load_channels`→`_run_query` seam shipped as B10-5 (#74); B9-2 `session.expunge`→DTO as B10-1 (#65); B9-3 cosmetics (#59). Plan doc retired (history in git) — see the **[Band 10 audit](docs/AUDIT_2026-06-19.md)** for remaining refactor work (`main_window.py`/`channel.py` splits).
- [ ] **Exclusions chip dead zone** — text area of the Exclusions chip is not clickable at cold launch; becomes clickable after a notification appears/dismisses. Root cause unknown (`setCheckable(False)` and solid-fill hover did NOT fix it). Likely z-order/geometry-timing in the bottom nav bar at startup; investigate `notification_widget.py` show/hide side-effects + bottom-nav-bar layout init.

## Data & Storage

- [x] **Image cache size cap + LRU eviction** — ALREADY SHIPPED (`image_cache.py:224-250`): 500MB default cap with oldest-20%-by-atime eviction. This line was stale for a long time. Remaining nicety: a settings UI control, and pruning images whose URL-derived key belongs to a removed provider.
- [x] **Re-map engaged content from a removed source → an active variant** — SHIPPED v0.23.0 (#392) as a Tools view ("Reconnect Engaged Content"). **DEVIATION from the design below, deliberate: there is NO default auto-map.** Every re-map is explicit and user-initiated, because silently rewriting favorites/history/ratings violates the sacrosanct-user-data rule. Also, engagement **merges** rather than moves — favorite ORs, `play_count` sums, `last_played` takes the later, the resume group (`watch_progress`/`watch_percent`/`watch_completed`) moves atomically from the further-along row, and an existing rating is never overwritten. A plain move would have destroyed a live row's own progress (watched 90% on A, sampled 5% on B, lose B → resume drops to 5%). Original design, retained for context: *(user direction 2026-06-29; see `project_hidden_content_recovery`)* — when a source is removed, its engaged channels (favorited/played/queued) are kept but orphaned (they still play via the stored URL while it lasts, and often a content_key sibling exists on an active source). Add a function (Settings or a dedicated flow) that **migrates the engagement** — favorite / history+play_count / queue / rating / resume position — onto a matching **active-source** variant. **Default auto-map** when there is a TMDB/content-id match (match the CONTENT, not the source channel) OR only a single variant is found; otherwise present choices. Flow: compute proposed mappings → **show what will be mapped → user approves → apply**. Leans on stored `content_key` (works today), with TMDB id as the stronger signal once that integration lands (Discovery → Canonical content IDs); an MVP can ship on `content_key` + single-variant heuristic. Ties to `project_one_source_per_account` (flag engaged-unavailable, don't delete) and the mirror-not-cage tenet.
- [x] **Quality token display refinement** — SHIPPED v0.16.0 (#197): display-layer translation only, stored tokens untouched. Original spec: `HEVC` and `RAW` are codec/bitrate descriptors, not viewer-facing quality levels; they appear in the On Now quality column and filter chips but are not meaningful to most users. Consider translating: `HEVC` → omit or show as a small "efficient" badge; `RAW` → omit or show as "Uncompressed". Do not rename them in the DB (they're derived from channel names) — apply a display-layer translation only.

## Sharing & Social

- [ ] **Share watch activity, recipes, and queues — send recommendations between people** *(user idea 2026-06-23)* — let a user **share what they've watched, share a recipe, share their watch-queue contents, and broadcast "what I'm watching now"** so people can pass recommendations around. The shareable artifacts: a **recipe** (a saved tag-facet category — the most naturally portable, since it's just an `includes/excludes` facet query + pinned/excluded title ids, see [Tag-cloud recipe builder] / `project_tag_cloud_recipe`), a **watch-queue** snapshot, a **history** slice (curated or "recently watched"), and a **now-watching** ping. **Keystone design constraint:** share **content identity, NOT stream URLs.** Two people rarely share the same provider, and stream URLs carry credentials — so a share must be a list of **canonical title identities** (`tmdb_id`/`imdb_id` once wired; normalized `title + year + media_type` as the stopgap) that the **recipient resolves against their OWN sources** (reuse the existing cross-source title-resolution / `content_dedup` path). A recipe shares even more cleanly — the facet query travels, and the recipient's library fills it from their own catalog live. **Transport, local-first:** start with a copyable **export blob / `.metatv-share` file / share-link** (no server required); a lightweight share service is a later stretch. **Privacy/guardrails:** opt-in, user picks exactly what's included, and the exporter **must strip all provider creds, stream URLs, and host info** — only canonical identity + user-authored metadata (recipe name, ratings, note) leaves the app. Ties to **Canonical content IDs (TMDb/IMDb)** (Discovery section — the share-identity backbone), the recipe/custom-category model, and PRODUCT_VISION's subordinate "headless backend + clients" direction (a share service would live there).

## Platform & Distribution

- [x] **Packaged Mac build launches** — SHIPPED v0.27.1 (#301). The app died instantly on every launch with `FileNotFoundError: metatv/gui/tokens/midnight.tokens.json` before any window appeared — the palette + sports data files were not being shipped into the bundle. Reported against 0.24.0 and 0.25.0. CI now launches the packaged app so a build that cannot start fails the release instead of publishing.
- [ ] **M3U playlist support**
- [ ] **Windows / macOS packaging** (AppImage / Flatpak for Linux too)
- [ ] **Linux release build in CI (owner steer 2026-07-31)** — `release.yml` is macOS-only (arm64 DMG). Add a Linux job on the same tag trigger that PyInstaller-builds MetaTV, vendors mpv (external binary spawned over IPC — `_resolve_mpv_binary()` finds it when frozen, else `$MPV_BINARY`/PATH), and packages an **AppImage** (memory: "Linux AppImage easy/unbuilt"). Upload it to the same GitHub Release (separate job, `fail-fast: false`, so a Linux failure never blocks the macOS DMG). Deferred out of v0.15.0 to avoid holding the launch on untested CI.
- [ ] **Multi-language UI** — i18n via Qt Linguist / gettext; RTL layout support for Arabic/Hebrew; locale-aware date/time formatting
- [ ] **Plugin system** for community providers

---

## Next Up

**v0.24.0 — refinement + cleanup (SHIPPED 2026-08-02).** Eleven What's New entries; verify with
`scripts/roadmap_audit.py --version 0.24.0`.

1. [x] **Theme application layer** (#253) — `QApplication` QPalette floor so unstyled widgets stop
   inheriting Qt's default light palette.
2. [x] **Six restart-only theme views** (#261) — Discover, Recipe, EPG, Preferences/Recommended,
   Provider editor, Sources manager, each with its own `refresh_theme()`.
3. [x] **Filter-path unification** (#260) — extracted `core/channel_visibility.py` and migrated
   `discovery_engine`, `preference_engine` and `tag.py` onto it. Closes tag.py's self-documented
   3-axis gap and the "Recommendations ignores global exclusions" bug class.
4. [x] **Collections as Discover shelves** (#256) — owner request; reads the stored
   `detected_collection`.
5. [x] **Comfy row chip system** (#257) — one chip system across surfaces, triple redundancy
   removed; plus the `QColor` fix (#257) for `rgba()` tokens that painted every overlay chip solid
   black, and the channel-list horizontal-scrollbar fix (#258).
6. [x] **Onboarding floor** (#262/#263/#264) — packaged app shows its version, a fresh install
   states plainly that it needs a source, and the Add Source control is actually visible.
7. [x] **Selection contrast** (#265) — `COLOR_ON_ACCENT` per palette; selected rows clear 4.5:1
   in all three themes.
8. [x] **macOS playback fix** (build-only, no What's New entry — `.github/workflows/release.yml:131`)
   — v0.23.0 shipped a bundle whose vendored mpv could not load its own dylibs (`dylibbundler -p
   @loader_path/libs/` produced doubled `libs/libs/` install names when the loader was itself a
   dylib in `libs/`), so playback silently did nothing on every macOS install. Prefix is now
   `@executable_path/libs/`, and the build fails if any install name contains `libs/libs/` or if
   the vendored `mpv --version` will not run.

**v0.25.0 — SHIPPED 2026-08-03 (owner UX pass).** Two What's New entries (#266, #267); verify with
`scripts/roadmap_audit.py --version 0.25.0`. Each item was a reported defect, not a plan.

1. [x] **False "+N episodes" alerts** (#267) — the Watch Queue reported "Rick And Morty +132 eps"
   and "Fallout +23 eps", climbing every launch. `baselines` was keyed by `provider_id` alone, but
   `content_key` is generous enough that one provider carries several listings of a show; each wrote
   to the same slot and each was compared against the same stale `prev`. The clamp then pinned the
   total to `sum(baselines)` — which is why the badge read as the provider's TOTAL episode count.
   Baselines are now keyed per mirror (`provider|source`), `_resolve_mirrors` dedupes on the full
   pair, and the migration zeroes the proven-corrupt counts rather than clamping them.
2. [x] **Stranded channel banner** (#266) — the channel-list banners live in `_list_layout`, not in
   any view, so `_hide_all_content_views()` never reset them: switching to Sources left
   "33 hidden by Global Exclusions" reporting a channel count over an unrelated view.
3. [x] **Add Source CTA read as disabled** (#266) — it borrowed `RECIPE_SAVED_ICON_BTN`, a
   de-emphasised icon-button role (transparent + `COLOR_FAINT`). Now its own `SOURCES_ADD_BTN`:
   solid accent fill with `COLOR_ON_ACCENT` text, contrast-asserted.
4. [x] **Series monitor fetched during interpreter shutdown** (#266) — `shutdown()` used
   `wait=False`, which stops new submissions but cannot interrupt the running batch, so it kept
   issuing live HTTP fetches past `Database.close()`. Now a `threading.Event` polled per entry and
   per mirror.
5. [x] **Source glyph on version chips with one source** (#266) — suppressed unless the versions
   genuinely span more than one source; the source is still named in every tooltip.
6. [x] **Results-list rows ran flush to both edges** (#266) — right-aligned cells anchor to
   `container.right()`, so the vertical scrollbar painted over them. `_ROW_H_PAD` inset applied at
   the paint chokepoint, so every density and the thumbnail path inherit it.

**v0.26.0 — SHIPPED 2026-08-03 (rolling).** Three What's New entries (#268–#270); verify with
`scripts/roadmap_audit.py --version 0.26.0`.

1. [x] **Rolling releases** (build-only, no What's New entry — `.github/workflows/release.yml:20`)
   — every push to `main` publishes to ONE moving release tagged `rolling`, so the tester bookmarks
   a single URL and always gets the newest build. Version tags still cut an immutable release, so
   nothing is lost. The identifier is kept but derived, never hand-chosen:
   `<version>+<UTC date>.<short sha>`, stamped into `metatv/_build_id.py` before PyInstaller so the
   packaged title bar names the exact commit. Old dmgs are deliberately not warehoused — any commit
   can be rebuilt via `workflow_dispatch`.
2. [x] **"Provider" vs "Source"** (#268) — Source in all 44 user-facing strings; Provider stays the
   code term. Guarded by `tests/test_source_vocabulary.py`, which walks the GUI AST, exempts logger
   text, and tests ITSELF against a planted violation. It found 11 tooltips the manual pass missed.
3. [x] **New Filter Values: Select all / Unselect all** (#268) — a new source can introduce hundreds
   of values; "exclude everything, then add back a few" was N clicks.
4. [x] **First run lands on Discover** (#268) — one-shot armed by the honest zero-sources branch,
   consumed when real channels arrive. Deliberately NOT disarmed by the Sources manager, since
   adding the first source requires going there.
5. [x] **EPG empty state** (#269) — `get_epg_readiness()` + a pure `epg_empty_state()` classifier
   tell apart no-sources / no-guide-URL / EPG-off / not-yet-fetched. Only the last suggests Refresh.
   Chip stays enabled throughout (owner call).
6. [x] **Add-source URL field above the list it feeds** (#269) — plus a plain-language TV-guide
   explainer, since the old tooltip presumed you knew what EPG and XMLTV are.
7. [x] **Row chips hover + click** (#270) — the delegate records the rects it painted and the view
   hit-tests them, so a hit region can never drift from the visible chip. Click routes into the
   EXISTING context-filter handlers, never a third path. A chip click filters ONLY (owner decision)
   — it does not change row selection, so it cannot collide with double-click-to-play. Chips that
   can't filter (year, ×N badge) explain themselves but show no clickable cursor.

**v0.26.0 follow-ups — SHIPPED 2026-08-03 (rolling).** Owner UX-testing the rolling builds found
four defects, three of them shipped by this same session's work. Entries #271-#274.

8. [x] **Chips filtered on the displayed code, not the stored tag value** (#271) — a quality chip
   filtered `"4K"` while the tag stores `"4K / UHD"`; a language chip filtered `"EN"` while the tag
   stores `"English"`. Both emptied the list. Region and genre coincide by accident, which is what
   made the mismatch look like it worked. `channel_name_utils.tag_value_for()` translates via the
   existing canonical tables; an unmappable token declines to filter rather than returning nothing.
   Collection additionally filtered on the wrong COLUMN (`detected_collection` vs the curated
   `ChannelDB.category`). **All context filters are now unified behind one applier**
   (`_activate_context_filter`) after the owner called out the duplication — the hand-rolled eighth
   copy was the broken one; a structural test now fails if a handler re-inlines the ritual.
9. [x] **Sibling region propagation contradicted a row's own locale** (#272) — `|EN| Aladdin` came
   back as German. `content_key` `"aladdin|movie|"` collapses 15 unrelated releases, and the pass
   fills an empty region from the most common sibling, so the library's dominant locale (DE) was
   stamped onto the `|EN|` and `|AR|` rows — an Arabic release reported as German, which then
   produced a bogus German *language tag*. A row carrying its own recognised locale code no longer
   inherits a contradicting region; rows with no locale of their own (`MULTI`) still do.
10. [x] **Person filter missed titles that name the person** (#273) — searching "Nicolas Cage" found
    a title whose filename carries it; filtering by the same name did not, because the filter checked
    only metadata/raw_data cast. Most rows have no metadata at all, so the filter was usually empty.
    Now matches the channel name too — **including live**: the owner correctly pushed back on
    excluding it, and the corpus proves the point, carrying whole categories of curated actor
    channels (`24/7 MOVIES/ACTORS VIP`, `AR| ACTORS 4K`). The media-type axis still governs
    independently, so they stay in Live.
11. [x] **Single-item action reset the list scroll** (#274) — `_category_assigned` was wired straight
    to `load_channels`, so every assignment requeried and `beginResetModel` scrolled to row 0. Adding
    one item to Watch Later from row 400 threw the user back to row 1. Now conditional on an actual
    membership change (category added to Global Exclusions).

**v0.26.0 second wave — SHIPPED 2026-08-03 (rolling).** Owner UX-testing the rolling
builds found nine more. Entries #275-#283.

12. [x] **Bad-region sweep** (#275/#276) — 78,327 rows carrying a region nothing on the row
    supported, then 4,752 more once the platform pass was widened. v1 consulted
    `channel_name_utils.PLATFORM_CODES` (11 streaming brands, no `SC`); the tag system
    classifies platforms from `config.BASE_PLATFORM_GROUPS` VALUES (85 tokens). Three
    vocabularies, and picking wrong failed silently. Only ever CLEARS — an empty region is
    honest, a guessed one is how the mislabels started. Derived language tags go with it.
13. [x] **Scroll reset** (#274/#275) — results list (`_category_assigned` → `load_channels`
    on every assignment) and every sidebar section (`BackgroundRefreshMixin` clearing the
    list twice per refresh). Both fixed; scroll offset captured before the clear.
14. [x] **Live theme switching** (#277/#278) — THE long-standing one. `theme.style()`
    registry replaces the unclosable 838-vs-22 sweep, plus a `_repolish_all_widgets()` pass
    because a palette push alone does not make an existing item view repaint. 465 call sites
    migrated; drift guard bans the raw form.
15. [x] **Style + Buffer menus** (#279/#280) — look-and-feel without opening Settings, and
    buffer reachable while a stream is stuttering. Both drive the SAME live-apply seams
    Settings uses. Filter-panel toggle fixed: it measured a width that could never reach 0
    (min-width 160), so it was one-way.
16. [x] **Person filter matches a title's own name** (#273) — including live, after the owner
    correctly pushed back: the corpus carries whole categories of curated actor channels.
17. [x] **Bracketed compound prefix** (#281) — `IT-[4K] - Title` matched nothing, so the whole
    prefix survived into the title. ~101 rows.
18. [x] **X-SUB means subtitles** (#282/#283) — `|AR|` under `|AR-SUB|` was tagged as Arabic
    AUDIO on an English film. Owner-confirmed. Re-filed under the subtitle facet.
19. [x] **Wrapping title clipped** (#283) — `Ignored` width (deliberate, the column-widening
    trap) left Qt no width to compute wrapped height against. `setHeightForWidth(True)`.

**v0.26.0 third wave — SHIPPED 2026-08-03 (rolling).** The queued v0.27.0 list, taken in one
pass. Entries #284-#289. Two items changed shape once measured against the real library
rather than the roadmap's own description of them — recorded here because the roadmap was
wrong, not the code.

20. [x] **content_key fragmentation** (#284) — NOT a key-format problem. "Same title" had two
    definitions: the key used `content_identity._normalize_for_key` while the propagation pass
    that picks siblings used `content_dedup.normalize_title`, a RAW-name cleaner. Run against
    the already-cleaned `detected_title` it double-strips ("Blade Runner 2049" → `blade
    runner`, merging the 2017 sequel with the 1982 film; "WWE: Unreal" → `unreal`). The bucket
    then held several tmdb ids and the remake guard correctly refused to guess — the ambiguity
    was MANUFACTURED. One normaliser: **+498 adoptions, 0 lost, 0 disagreements**. Second half:
    an id learned by a *fetch* never reached its siblings (propagation ran at ingestion and
    after refresh, never after enrichment) — exactly why "The Lobster" sat as a `'fetched'`
    tmdb row beside two idless copies of itself. **Rejected after measuring:** lifting a
    trailing year out of the title — 1,754 rows re-keyed, ZERO fragmented titles fixed
    (3931 → 3931).
21. [x] **Name-derived cast** (#285) — `detected_name_cast` was stored and read by NOTHING.
    Now a LOW-confidence `person` tag under "Named in Title", never merged into
    `MetadataDB.cast`. Only person-SHAPED residuals: of 917 distinct real values about half are
    language/format/studio words (POLSKI 918, 4K 652, DOKUMENT 531), and a wrong facet is a
    false statement, not a low-confidence guess. Also fixed a latent bug in
    `category_facet_refacet`, which re-derived tags without the name/audio feeders and so
    silently DELETED those tags from every row it touched.
22. [x] **Live theme for composed stylesheets** (#286) — the ~370 f-string `setStyleSheet`
    sites, solved at the chokepoint instead of ~300 hand edits: `apply_theme` computes what
    each colour VALUE became and rewrites it wherever it survives, guarded against ambiguous
    and theme-invariant values. Needed `COLOR_LIGHTBOX_TEXT/_HI` respelled to full hex —
    identical colours, but the `#fff`/`#ccc` shorthand collided with the themed text ramp and
    blocked the app's two commonest text colours from ever updating.
23. [x] **Discover shelf filter** (#287) — **the roadmap's own remedy does not work.** Raising
    `MIN_COLLECTION_SHELF_MEMBERS` was the plan; measured, the floor is already 2 and the count
    barely moves (1,882 shelves at ≥2, still 1,440 at ≥20). No tail to trim, so a cutoff hides
    real collections for nothing. Filter box instead; not persisted (a filter restored at
    launch reads as an empty Discover).
24. [x] **Layout menu** (#288) — sidebar/details/filter panels, ticked from the live splitter
    rather than a cached flag. Filter panel moved out of Style. Uncovered and fixed a real
    bug: `expand_panel` never reclaimed the space its neighbours absorbed, so a restored panel
    came back narrower every cycle (416px → 327px) — affecting splitter handle clicks too, so
    it predated the menu.
25. [x] **Watch Queue ordering** (#289) — owner reported queue items they had never queued.
    Investigated against the real library: NOTHING fabricated them (611 rows, all live
    channels, 610 of 611 holding their recorded name, no two rows sharing an insertion second
    so no bulk add ever ran, no auto-enqueue path, no `content_key` involvement). Real cause:
    "Never Watched" rendered in raw append-only `position` order, so the top was permanently
    the OLDEST items and anything queued today landed ~600 rows down. Now newest-first,
    unavailable entries grouped, both headers carry a count.
26. [x] **CI-only test failure blocked two releases** — the #283 wrap test hardcoded 320px and
    assumed a string wraps there. It does locally; on the macOS runner it fits one line. The
    release workflow gates the build on the suite, so `5f49062` and `2906755` never published
    and the tester sat on `6211f87` for three hours while `main` moved twice. Widths now derive
    from the font's own `horizontalAdvance`. Same family as the px-pinning rule: an assertion
    that hardcodes a value the ENVIRONMENT owns passes where written and fails where it runs.

**v0.26.0 fourth wave — SHIPPED 2026-08-03 (rolling).** The three buildable v0.27.0 items,
taken in one pass. Entries #290-#291 (the third is a contract + test, no user-visible
behaviour). Two of the three were again not what their roadmap entry described — see below.

27. [x] **Scroll reset — the section that was missed** (#290) — the entry claimed the Watch
    Queue AND Recommended both reset. Measured: the queue has preserved scroll since #275.
    What #275 called "one shared chokepoint" was `BackgroundRefreshMixin`, and
    `RecommendedSection` is that mixin's DOCUMENTED exception (its `None` is a valid empty
    state, not a load failure), so it inherited none of the fix — including for the refresh
    its own "Show N versions separately" action fires. Moved capture/restore down to
    `ScrollPreservingMixin` on `CollapsibleSection`, which every section inherits, so an
    exception to the refresh skeleton can't opt out of scroll behaviour again. The existing
    test's own docstring named Recommended as covered; it wasn't.
28. [x] **Watch Queue find-in-queue** (#291) — **the roadmap's remedy measured wrong again.**
    "The queue has no ceiling; decide on archiving/ageing." Against the real 612-entry queue:
    74 rows in the last 7d, 102 at 7-30d, 436 at 1-3mo, and **0 older than 3 months**. A
    3-month cutoff archives nothing; a 1-month cutoff hides 436 of 612. It is not a stale
    tail — it is a queue filled faster than it is drained, every row added deliberately, so
    ageing it out would be censorial (mirror-not-cage). Filter box instead: hides nothing,
    headers retitle to `(N of M)` while active, survives a refresh, not persisted.
29. [x] **Two queue read paths disagree on scoping** — reviewed and found CORRECT, so the
    invariant was pinned rather than the call sites made cosmetically identical.
    `get_all(hidden_provider_ids=…)` ANNOTATES and never drops (record view, DR-0007); the
    sidebar/favorites pass it because they RENDER availability, `load_queue_ids` consumes ids
    only. The real risk was a future "tidy-up" turning the argument into a filter, which would
    silently empty the Unavailable group — `tests/test_queue_scoping_contract.py` now fails if
    anyone does, and it also pins `clear_unavailable` (the one path that deletes) to exactly
    the rows `get_all` marks unavailable.

**v0.27.1 — SHIPPED 2026-08-15 (rolling).** Source-reliability cluster, opened by an owner bug
report ("diagnostic says the stream is unreachable but it plays") and widened by what that turned
up. Six What's New entries (#301–#306); verify with `scripts/roadmap_audit.py --version 0.27.1`.
Detail on each lives in **Playback & Queue → Source reliability & stream diagnostics** above.

1. [x] **Packaged Mac build launches** (#301) — shipped without its palette/sports data files.
2. [x] **URL-cycling chokepoint** (#302, PR #413) — and the discovery that the refresh path's URL
   stats were never persisted at all (SQLAlchemy saw no change on an in-place JSON mutation).
3. [x] **Series diagnostics targets the played URL** (#303, PR #413) — the original report.
4. [x] **Episodes can be resumed** (#304, PR #413).
5. [x] **Recency/latency host ranking** (#305, PR #416) — plus two integration fixes that carry no
   What's New entry of their own (no separate user-visible behaviour), cited by anchor per the
   release-claims rule: the settings were **inert as merged** — no call site passed a `Config`, so
   editing `config.yaml` changed nothing — now resolved once at startup into a frozen policy
   (`metatv/core/url_policy.py`, installed at `metatv/__main__.py:42`); and the #302 drift guard
   matched source *lines*, so it fired on three comments that merely describe `ordered_urls()` —
   it now matches `ast.Call` nodes (`tests/test_url_cycle.py:233`).
6. [x] **Failover sticks to the item** (#306, PR #416).

**Method note worth keeping.** Four defects in this batch were found by verification rather than
reported, and three shared one shape: *a test too narrow to see the defect it nominally covered* —
URL stats asserted as counts with no timestamp, a drift guard matching source lines so it fired on
comments, and a test suite that reimplemented the logic under test and therefore passed against
broken code. The mutation check (break the production branch, confirm the test goes red) is what
caught the last one; a green suite proved nothing. Same family as the rating fan-out problem.

**v0.28.0 — next.**

- [ ] **Cross-view state sync engine (Bus + DTO)** — fully scoped this session, not started. Writes
  are already chokepointed (`_toggle_rating` is shared by details pane, lightbox and trail map); what
  is missing is read-side invalidation — every mutation handler hand-picks a refresh list, so e.g.
  disliking from the Watch Queue leaves the details pane's buttons stale. Design settled with the
  owner: widen `ChannelActionState` into one canonical per-channel user-state DTO; every mutation ends
  in `publish(channel_id)` and drops its hand-picked tail; surfaces **self-register** weakly rather
  than being enumerated (the `theme.style()` lesson — an enumeration never sees what nobody remembered
  to add); two-tier delivery, synchronous delta for instant echo then an authoritative off-thread
  re-read through the existing `_run_query` seam. Most of the receiving end already exists and is
  simply never called (`details_pane.apply_action_state` already guards on the wrong channel_id;
  `channel_model.update_*` already no-op on unknown ids). **Owner decision, settled:** judgment flags
  (like/dislike/not-interested) apply at **title level** via `content_key`, but must NOT fan out into
  N rating rows — see the item below.
- [ ] **Ratings must not be double-counted across variants** — `build_attribute_weights`
  (`core/preference_engine.py:331-346`) builds one signal per `UserRatingDB` row and accumulates
  `sig * weight` per attribute, so N rated variants of one title would count N times: genre weights
  scale by N, `disliked_count` inflates, and `actor_support[name] += 1` fires N times, defeating the
  corroboration gate that exists to prune performers seen in only one rated title. **This already
  double-counts today** — `recommend()` imports the dedup helpers but the weights path never uses
  them. Store one rating row, collapse at read on `COALESCE(content_key, 'id:' || id)`. Do not re-key
  `UserRatingDB` on `content_key`: the key is mutable (it flips to `tmdb:` form when enrichment lands)
  and a rating keyed on it can orphan; keeping the row on `channel_id` also needs no migration of user
  ratings. Related symptom: `disliked_ids` is channel_id-keyed, so disliking one variant leaves its
  siblings fully recommendable — the app keeps asking after you said no.
- [ ] **"Reconnect content seems to mangle a bunch of the content"** — owner-reported,
  UNEXAMINED. No detail captured yet; ask what looked wrong before digging. Blocked on the
  owner, not on the code.
- [ ] **Which reload changes a title under you?** Unconfirmed leftover from the scroll report:
  whether the TMDb-match / title-update refresh the owner saw comes from a third path (not the
  sidebar sections, which are now covered). Needs a reproduction before it is worth chasing.
- [ ] **Platform rollup for Discover shelves** needs its own Q-tag review (carried over; never
  had a design pass).

**Owner-owed, not buildable by the coding agent:** TMDb/OMDb have never made a real network call
(#395 was mocked-aiohttp only). The Settings **Test** button already exists at
`settings_dialog_tabs.py:486` — paste a key, click Test, enrich one title. Until then that work is
unverified regardless of its green suite.

**Biggest genuinely-unbuilt features** (see NOT BUILT annotations above): download/save VOD, live
DVR, mini-player, global hotkeys, keyboard shortcuts, channel-list grid view, Similar Content
metadata sibling, preference-scored Explore columns, Discover pre-warm, Hidden Management view.
