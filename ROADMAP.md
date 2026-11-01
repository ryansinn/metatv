# MetaTV Roadmap

What is left to build. **Future only:** finished work is deleted from this file, never ticked —
git history and the What's New entries are the record. At session wrap, remove what a session
finished and narrow partial items to what remains (docs/SESSION_WRAP.md, step 3).

> **Product vision & direction:** [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) — the
> lean native ambient-companion player; complexity → a mind-reading Discover; chef↔grocery and
> comfort↔explore axes; good on raw data. Settled designs: [docs/DESIGN_INDEX.md](docs/DESIGN_INDEX.md).
> Code-health findings and the duplication ledger live in [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md).

## Owner decisions waiting

- [ ] **Should the background pollers exist at all?** Series monitor, eager genre backfill and the
  signal check are all **off by default**. One full source refresh (1 request, ~34 s) answers what
  one series-monitor pass asks with 234 requests over 4-39 minutes, on one-connection sources.
  First check for the series monitor: whether the Xtream series *list* carries enough to diff
  episode counts without `get_series_info` — if so it survives as a rewrite. Guard:
  `tests/test_background_polling_is_off.py`.
- [ ] **Signal check (dead-air detection) — PARKED, not a task.** Disabled since the day it shipped
  (#617): a probe holds a one-connection source's only slot, and ffmpeg's 145/146 "could not open"
  exits were read as "no video". Revisit only as a design conversation. `hide_dead_events` is wired
  and waits for a working probe.
- [ ] **Version Preferences — rework (mockup before any build).** The quality half is unified;
  still open: rename "preferred prefixes" to Preferred Language (+ Region) on the stored
  `detected_region`; replace the substring quality test (`preference_engine.py:207`
  `preferred_version_quality in channel.name` — "HD" boosts Baghdad and every FHD row); frame
  language as the axis that matters (42% of multi-variant titles differ by language, 5% by
  quality); rebuild the UI in the chip grammar.
- [ ] **Preferred language / region as a POSITIVE preference** (after the UX overhaul). An ordered
  (language, quality) preference consulted as a promotion tier at the collapse chokepoint, so every
  surface puts the preferred copy forward. Quality stays optional. Never reuse
  `metadata_tmdb_language` (fetch language, not variant choice).
- [ ] **Reconnect content mangle — detach-on-recycle + a "lost its source" review list.** Renewing
  a source with a new account reuses `stream_id`s, so favourites/queue land on different titles
  (detection logs `STREAM-ID REUSE`). Design proposed as RECYCLE-1: a record per recycled engaged
  row, flags cleared on the new occupant, a review list (Find again / Keep the new one / Forget).
  Q1-Q4 await the owner. Never freeze the name; never silently rematch by `content_key`.
- [ ] **Yearless movie key collapses unrelated films.** Without a year `content_key` falls back to
  the bare title: 27,375 rows in 8,007 multi-row groups. Options: refuse to collapse without a
  year; require a corroborating signal; fill the year first. Check `series`/`live` before changing
  the rule.
- [ ] **Tier / package detection** — reads the name; the signal is in the category (20×), and half
  the vocabulary is not tier words. Owner: leave untouched for now (nothing reads the field).
  Evidence: the "Where Tier Lives" artifact.
- [ ] **TMDb/OMDb have never made a real network call** (owner-owed): paste a key in Settings ▸
  Metadata, click Test, enrich one title.

## Metadata & Enrichment

- [ ] **Genre canonicalization gaps** — Chinese, Japanese, Persian and Hindi-script genres; duplicate
  spellings (`Sci-Fi_Fantasy` / Science Fiction / Fantasy, `Action` / `Action_Adventure`); a
  developer scan for high-volume unrecognized genres.
- [ ] **Xtream VOD/live info** — `get_live_info()` is never called, and the full `get_vod_info()`
  payload is used only for its TMDb id.
- [ ] **Canonical IDs beyond the provider's TMDb id** — IMDb ids, and external-API ids for rows
  whose provider sends none.
- [ ] **Name-parser gaps (owner-approved backlog)** — colon-platform grammar, superscript quality
  variants, zero-width characters, four-hash markers, exclusion residue; measured numbers per row in
  memory `project_parsing_gaps_backlog`. Parser debt degrades dedup, search and tags, not just display.
- [ ] **Metadata cache management** in Settings (the key fields and Test buttons exist).

## EPG & Watch Alerts

- [ ] **Preferred playback source for a watched show** — a programme airing on several channels
  plays the first airing; remember the source the user picked (or rank by quality / previously
  watched / host reliability, reusing `UrlCycler`'s ranking).
- [ ] **EPG → Watchlist tab pass** — play buttons drawn where they land (three positions in one
  card) and a card-level play role beside the row-level one. Keep the accident that works: upcoming
  rows have no button, so presence means "on now". "OFF AIR" fold is ledger F14.
- [ ] **Pinned watchlist channels** — `epg_watchlist_channels` is still a config list; move it with
  the patterns.
- [ ] **Rule query syntax (Option C)** — a typed query (`"nrl" AND NOT "highlights"`) that parses onto
  the stored rule fields. Optional; nothing owed if never built.
- [ ] **Filler-match patterns in the UI** (config-file only today).
- [ ] **Guide channel preview** — debounced autoplay into the external mpv window while browsing.
- [ ] **EPG accuracy flagging** — per-channel "unreliable EPG" flag with mismatch reports; later,
  AI-assisted analysis of accumulated flags to suggest `epg_channel_id` mappings.
- [ ] **A LIVE platform surface** — "what is on now on this platform", its own design (not the VOD
  platform shelf with a filter).
- [ ] **Live event status and scores from a sports API** — real state ("3rd Quarter · 4:12"), team
  badges; scores hidden by default, never in a notification. Enrichment, never a dependency.

## Playback & Queue

- [ ] **A queue that plays through** — sequential airings, "start this when it airs", and a setting
  for announce / pop-up / silent. Wire it to the existing programme-boundary timer
  (`sidebar/alerts.py` `_schedule_boundary`); consult `ConnectionAccountant`, never a second counter;
  never start playback the user did not ask for.
- [ ] **Ambient mini-player** — low-chrome always-on-top corner window that expands to fullscreen.
- [ ] **Global playback hotkeys** — media keys without focusing the player.
- [ ] **Music as a first-class media type.**
- [ ] **(Stretch) Desktop-embedded playback widget** (Linux/KDE).
- [ ] **Stream diagnostics cycle hosts** — `core/stream_diagnostics.py` still tests one bare URL; thread
  the provider through `UrlCycler` and report per host ("reached 0 of 20" vs "18 fine, this one slow").
- [ ] **A persistent "may be stale" mark** on a source that keeps failing playback — or is the
  failure toast's Refresh action enough? (owner question)

## Series & Episodes

- [ ] **"Most current source" for a series** — per-version season counts and a "most complete" mark
  on the version chips, weighing gaps (ES South Park reaches 25 but lacks 5-9). Compare sources
  already drilled into; TMDb would make "most current" exact.
- [ ] **`inspect_series.py --live`** — dump the raw `get_series_info` season/episode keys; also the
  cross-source completeness comparison.
- [ ] **Loose VOD episodes → Series (SHELVED)** — 5,115 episode rows filed as movies, 346 shows,
  already one card per show. Needs synthesized series/season/episode rows and a `drill_into_series`
  branch; 5,108 rows are Turkish, which the owner's exclusions hide. Memory: `project_loose_vod_episodes`.

## Discovery & Recommendations

- [ ] **Similar Content — a metadata sibling to Similar Titles** in the details pane (DR-0003):
  Similar Titles stays crude title-token linkage; Similar Content uses genre/cast/director.
- [ ] **"Why similar" per title** in the lightbox, tied to a "why was this recommended?" explainer.
- [ ] **Explore columns blend in preference-scored matches** — `explore_view.py` still uses only
  title-token adjacency.
- [ ] **In-lightbox breadcrumb** — the one-line inline trail (the trail map covers the full view).
- [ ] **Discover pre-warm setting** — opt-in background fetch of collapsed shelves after paint.
- [ ] **History as a context engine** — watch counts, time patterns and self-reflection beyond the
  grouped archive.
- [ ] **Watch Queue aging / organization** — date-added grouping, reorder, age-out; live channels
  should not sink to the bottom of a positional list.
- [ ] **Dedup transparency toggle** — see raw scored candidates, with a "why recommended" explainer.
- [ ] **User categories in recommendations** — infer a category's genre and let the user confirm;
  "More like this category" shelves; a bulk mood editor.
- [ ] **AI taste profiles** from category names, moods and history once an LLM provider is wired.
- [ ] **Launch-time feedback prompts** — "You watched X — what did you think?", opt-in, rate-limited.
- [ ] **Trending content** — needs an external feed.

## UI / UX

- [ ] **V3 overhaul — rows and details pane** — the foundation shipped; the design is settled and
  approved (memory `project_v3_design_settled`) — build against it, do not re-mockup.
- [ ] **Search typo tolerance** — real edit distance (trigram or edit-distance index); never a
  "fuzzy" toggle that does not do it. Measurements: the "Finding Tron" artifact.
- [ ] **Chevron treatment** — sidebar headers dropped theirs; details pane, dialogs, shelves and the
  watchlist still use mixed treatments. Inventory and mockup first.
- [ ] **Cross-view sync phase 3** — a bulk-aware seam for bulk favourite/queue/hide/watched (one
  publish per set, not per channel), and a list-membership seam for the views that are still
  hand-listed in mutation handlers.
- [ ] **Sidebar register split** — rail as launcher/index, live vs curated vs system status
  (DR-0001); plus reusable shelf-style full views for Queue / History / Favorites.
- [ ] **Reorder sidebar sections** (PARKED) — drag on the header (split press-click from drag past
  `startDragDistance`); the shared right-click menu now reaches every header.
- [ ] **Sidebar sections in a right-hand column** — would turn `sidebar_sections` order into a
  placement per section (migrate the field, do not extend it).
- [ ] **UI vocabulary standard** — "Exclude" for Global Exclusions, "Hide" for one row, retire
  "Block"; document in UI_UX_GUIDELINES.md and apply across older menus.
- [ ] **Unified filter panel across views** — the input is one widget; EPG, Discover and
  Recommended still carry their own panels.
- [ ] **Explain how filtering works** — empty-state notices for the remaining axes, the chip-line
  explainer, a first-run card and a Help entry (the adult axis is done).
- [ ] **Hidden-content recovery surface** — one place to see and restore everything hidden, per axis.
- [ ] **Filter improvements** — search within excluded results; "Copy filters from…" across views;
  "Promote to global exclusion"; provider-level filtering with several sources.
- [ ] **User-defined prefix groups** — UI over `user_prefix_overrides` to move codes between groups.
- [ ] **Unrecognized prefixes** — ~149 codes remain (Source Analytics lists them); the owner
  names them when there is time.
- [ ] **Channel-list grid view** (Discover's browse grid exists; the channel list is a plain list).
- [ ] **Details-pane poster size** — reduce the fixed 431px, or offer Small/Medium/Large.
- [ ] **Session sub-attributes** — `[FP1]`, `[RACE]`, `[Prelims]`, `[Main Card]`, `[EAST]/[WEST]` as a
  stored tag so sessions can be filtered.
- [ ] **Tag hierarchy rollup** — tags carry type and provenance; rollup (sub-facet → parent) is not
  implemented. Memory `project_tag_concept_alias_model`.
- [ ] **User-side category management** — deferred to the tag system.
- [ ] **Exclusions chip dead zone** — the text area is not clickable at cold launch until a
  notification appears and dismisses. Root cause unknown (z-order/geometry timing suspected).

## Code Health

- [ ] **Document the title pipeline end to end** — ingestion → identity → storage → query →
  exclusion → collapse → render, with a table of every exclusion axis and where it applies, the
  ordering constraints, and a glossary of misleading config keys.
- [ ] **`main_window_metadata.py` hand-rolls the async seam** — move its `executor.submit` +
  bespoke-signal pairs onto `_run_query`; two swallow errors and leave the previous channel's state.
- [ ] **`_RecRow`** (preferences) — onto `build_chip_row`, the one row builder.
- [ ] **Collapsible headers** — 3 files outside `details_section_header.py` / `sidebar/base.py`
  still hand-roll the expand/collapse glyph; widen `CollapsibleHeader` and add the AST guard.
- [ ] **Poster well written four times** — one `PosterWell(size, FILL|FIT)` over
  `ImageCache.subscribe()`; the deliberate FIT sites stay FIT.
- [ ] **Skeleton-host attribute probes** — 104 left (budget in
  `tests/test_skeleton_host_attribute_probes.py`); convert per site, lowering the budget.
- [ ] **Blind `except Exception` handlers** — narrow each to its intent, boundary vs inline, one at a
  time (never as a sweep).
- [ ] **UI-thread work** — `preferences_view` runs `get_rec_suppressed()` and `record_impressions`
  on the UI thread.
- [ ] **Small defects from the 2026-08-31 audit** — `trail_map_view._on_image_loaded` returns on
  `not isVisible()` before handing the image to waiting posters, so a poster loaded while the trail
  map is hidden keeps its placeholder; the Discover Browse filter box is undebounced
  (`debounce_ms=0`; every other search box uses 300 ms).
- [ ] **A title that changes under you on reload** — an unconfirmed report from the scroll work:
  some refresh path (TMDb match / title update) re-titles a row in view. Needs a reproduction first.

## Data & Storage

- [ ] **Image cache** — a Settings control for the cap, and pruning images of deleted sources.
- [ ] **Export user state to plain text** — watchlist, presets, favourites, ratings, queue, hidden,
  sources minus credentials: a readable backup now that the YAML no longer holds them. Never
  include credentials.
- [ ] **Filter presets** — saved, named filter sets as a chip row above the facet strip. `FilterDB` /
  `FilterRepository` exist with zero callers; check the `rules` JSON can express the whole query
  before adopting it.

## Sharing & Social

- [ ] **Share watch activity, recipes and queues** between people.

## Platform & Distribution

- [ ] **M3U playlist support** (only Xtream exists).
- [ ] **Python 3.15** — 3.15.0 shipped 2026-10-09; everything runs 3.14 since #1020. Bump the
  three workflows and ruff's `target-version` once PyInstaller ships 3.15 wheels; then try its
  lazy imports on startup time.
- [ ] **Multi-language UI** — Qt Linguist / gettext, RTL, locale-aware dates.
- [ ] **Plugin system** for community providers.
