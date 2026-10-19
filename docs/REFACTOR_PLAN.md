# MetaTV — Refactor & Duplication Ledger

Open work only, re-checked against the code on 2026-10-19. Closed rows are deleted;
a code comment citing a row ID that is not here refers to this file's git history
(`git log -p docs/REFACTOR_PLAN.md`).

## Running duplication ledger — rules

- Every duplicate found is fixed in the slice or logged here, never dropped.
- Say what actually differs: a pure duplicate and a policy difference need different fixes.
- A mistake that recurs at different call sites is a **class**: log the predicate, its
  census count and the sites — or better, close it with a guard (GUARD-6, #830).
- IDs are never reused. Next free: **D69**, **F55**.

## Ready to build

Nothing queued (the last ten closed 2026-10-19).

## Needs investigation first

| # | What | Known so far |
|---|---|---|
| D57 | GUARD-4 matches stored fields by bare name | False "wired" across models; false "unwired" through `setattr` (#912). Needs type resolution. |
| D60 | State changes not reaching on-screen surfaces — reader half | Owner-requested audit: every watch/queue/alert/favourite surface repaints on change. Writer half is guarded. |
| D61 | Pre-play probe spends the only connection on one-slot sources | Skip it when `max_connections == 1` and no alternate URL; measure on the owner's account first. |
| D62 | mpv's yt-dlp fallback re-hits the provider after a failure | `--ytdl=no` for provider streams only (trailers need it). |
| F4 | `REGION_FULL_NAMES` likely has more ISO-vs-IOC alpha-3 gaps | One systematic pass. |
| F6 | Selection colours can be overwritten by a later stylesheet | Audit every item view per palette; guard the ordering. |
| F19 | Concurrent background writers starve the catalogue insert | Writer count, not write size; see memory "SQLite single-writer budget". |
| F21 | `raw_data` (36% of `channels`) can't be deferred everywhere | Store the provider rating at ingestion first. |
| F32 | Episode-label residue in titles ("… 77 Bolum") | ~36 rows; belongs with the parsing-gaps backlog. |
| F36 | List-selection palette pin freezes after the second theme switch | Qt drops palette roles after repeated stylesheet changes; try paint-time colours. |
| F47 | `discover_collapsed_shelves` is unused data but still the dialog's backing store | Derive the Collapsed column; migrate from the raw YAML. (F48's fallback, its other reader, is gone.) |
| F49 | Genre has two separately versioned derivations | `detected_genres` vs genre tags; couple the version counters. |
| F54 | A source numbers a franchise in the name ("01 EN - Friday The 13th (1980)" … "14 EN - …"); the number is lost and breaks the parse | **Template: the Friday the 13th films** — 28 movies, all TREX category "\|EN\| HORROR/THRILLER", shape `NN EN - Title (year)`; no other numbering shape in the library (2026-10-19). The number blocks prefix parsing (region blank, "02 EN - …" stays in `detected_title`), and the order is not reliable even via the original-name sort: "01 EN" loses its collapse group to "EN - Friday The 13th 4K (1980)", so it shows un-numbered and sorts elsewhere. **Owner's plan (parked):** store the number at ingestion in a `franchise_order`/series-order field (from whichever copy carries one), strip it from the title, show it as a quiet visual indicator ("#01") in results when populated, and sort a franchise run by it (year as fallback). Needs: the field + ALTER TABLE entry, parser support for a leading `NN ` before the prefix, a reparse bump, the indicator and the sort. |
| GUARD-7 | PyQt sometimes segfaults at interpreter exit | Get C frames under gdb; find the QObject that outlives the app. |

## Needs an owner decision

| # | Question |
|---|---|
| D22 | Should an invisible sidebar sub-list be sized at all? (decides whether `alerts.reapply_row_budget` can go) |
| F2 | One "in N minutes" wording for the EPG watchlist and the shared helper? |
| F10 | Quality chip beside the title in every sidebar list, as in Watch Alerts? |
| F14 | EPG watchlist "OFF AIR" fold → `GroupHeading`? |
| F18 | A global `sys.excepthook` that logs instead of aborting? |
| F31 | Who owns the sports vocabulary — the curated league data or the gate lists? |
| F41 | Details-rail buttons from colour emoji to vector icons? |
| F51 | Is the `"header"` tag feeder provider-stated or inferred? |
| — | A sweep for tags nothing references? Recommended: not until the tag concept model lands. |

## Kept on purpose — don't "fix"

- **D25** — `_ordered_sections`' empty-bucket filter: unreachable today, a bug the day it isn't.
- **D32** — `signal_check_manager.LIVE_WINDOW` sets probe volume, not event display.
- **D35** — two category→region readers: exclusions read `AR` as a region, facets must not.
- **D44** — single-item `TagRepository` methods are public API.
- **D46** — "unused" Qt overrides, plugin contracts, halves of used pairs and test seams.
- **F23** — metadata stored per row (~230 MB redundant): disk, not correctness.
- **F40** — two `variant_count`s: merging means changing the recommendation engine.
- **F43** — the provider icon picker's emoji is the value being picked.
- **F50** — two "Full (CODE)" builders: only the details one honours config overrides.
