# MetaTV — Refactor & Duplication Ledger

Open work only, re-checked against the code on 2026-10-19. Closed rows are deleted;
a code comment citing a row ID that is not here refers to this file's git history
(`git log -p docs/REFACTOR_PLAN.md`).

## Running duplication ledger — rules

- Every duplicate found is fixed in the slice or logged here, never dropped.
- Say what actually differs: a pure duplicate and a policy difference need different fixes.
- A mistake that recurs at different call sites is a **class**: log the predicate, its
  census count and the sites — or better, close it with a guard (GUARD-6, #830).
- IDs are never reused. Next free: **D70**, **F62**, **WIP-7**.

## Ready to build

### D69 — the audio exemption is missing from two exclusion sites (class)

**The rule.** A Global Exclusion hides a copy by its prefix (`NL`, `GR`, …). When a stream
scan proves the copy's audio is NOT the language that prefix denotes, the measurement wins
and the copy stays visible: `StreamInfoRepository.prefix_exempt_ids(excluded_prefixes)`
(`core/repositories/stream_info.py:33`, predicate `stream_info.audio_contradicts_prefix`)
returns those ids, and the exclusion predicates take them as `keep_ids`
(`filter_utils.channel_exclusion_criterion`, `filter_utils.py:270–324`;
`channel_visibility.apply` via `VisibilityScope.exclusion_exempt_ids`;
`main_window_channels._apply_python_exclusions` via `heard_keep`).

**Owner's case, 2026-10-21 — works today.** `4814008b-…_2173106` "NL - DIGGER (2026)": NL is
excluded, the probe heard English (`stream_info` row, source `probe`). Checked read-only on
the owner's library: hidden without the exemption, visible with it, also tagged
`language=English`. 100 copies are exempted this way on that library.

**The class — predicate:** a call to `channel_exclusion_criterion` /
`is_channel_excluded` (or a builder of one) that is not handed the exempt ids. Census
2026-10-21, `grep -rn "channel_exclusion_criterion(\|is_channel_excluded(" metatv`: 5 call
sites, 3 pass the exemption, **2 do not**:

1. **Collapse election — the real bug.** `repositories/channel.py:116`
   `_collapse_rank_penalty` builds tier 2 ("will be dropped") as
   `NOT channel_exclusion_criterion(excluded_prefixes, cls)` at `:169` with no `keep_ids`,
   so an exempt copy ranks as dropped. When a title's other copies are also under excluded
   prefixes, both rank 2 and quality/id decides; if the non-exempt copy wins, the Python
   pass (which DOES honour `heard_keep`) drops it, and **the title vanishes although its
   English-audio copy should show** — the same failure the penalty was written to stop
   (18,486 titles, see the comment at `channel.py:576–597`). DIGGER escapes only because
   its other copy ("|GR| Digger", ProSat) is on an expired source and is removed by the
   WHERE before the collapse.
2. **EPG "On now".** `gui/epg_on_now_mixin.py:398` calls
   `is_channel_excluded(category, region, global_excluded)` with no exemption. Live
   channels get `stream_info` from playback and signal checks, so an excluded-prefix live
   channel measured in another language is hidden here and shown in the channel list —
   two surfaces disagree. Lower stakes; same fix shape.

**The fix.**
- `_collapse_rank_penalty`: add `exempt_ids=None` and pass it as
  `keep_ids=exempt_ids` to the `channel_exclusion_criterion` at `:169`, so an exempt copy
  ranks 0/1 like any visible copy. Thread it through `exclusion_sets`: the caller
  `get_all(... collapse_variants=True)` builds that dict at `channel.py:481`; add an
  `exclusion_exempt_ids` parameter to `get_all` beside `excluded_prefixes`.
- `gui/main_window_channels.py:574–584`: `heard_keep` is already computed at `:574`,
  before `_rank_excl` is built at `:578` — add `'exclusion_exempt_ids': heard_keep or None`
  to `_rank_excl` and pass it into `get_all`.
- Find every other `get_all(..., collapse_variants=True)` caller that passes
  `excluded_prefixes` (Discover workers, search) and give it the same id set, resolved from
  `prefix_exempt_ids` in the same session — never a second definition of "exempt".
- `epg_on_now_mixin.py:398`: resolve `prefix_exempt_ids(global_excluded)` once where
  `global_excluded` is resolved (off-thread, with the region map) and skip
  `is_channel_excluded` for those channel ids, as `main_window_metadata.py:350–358` does.
- **Close the class with a guard** rather than trusting the census: an AST test that
  fails when `channel_exclusion_criterion(...)` is called without `keep_ids=` or
  `is_channel_excluded(...)` is called outside a branch that consults an exempt set,
  with an explicit allow-list for sites that cannot see stream data. (GUARD-6 is the
  worked example.)

**Test that proves it** (real `Database` on `tmp_path`): one title (shared
`content_key`), two copies — copy A prefix `NL` with a `stream_info` probe of English audio,
copy B prefix `GR` with no probe, B with the higher quality so it would win on quality;
exclude `NL` and `GR`; `get_all(collapse_variants=True)` through the real load path must
return the title, represented by A. Must FAIL on today's code (B elected, then dropped).
For the EPG site: an excluded-prefix live channel with English `stream_info` appears in On
now.

**Why it matters.** "A verified fact beats the guess" is a rule the owner relies on
(an English film filed under a Dutch category), and today it holds on one surface and
silently fails on the collapsed list and On now — a title disappears with no row, count
or hint explaining why.

## Work in progress — designed, waiting on the owner's answers

Nothing here is built. Each row is a design or a set of open questions; build only after
the owner answers. Recorded 2026-10-21.

| # | What | Where it stands |
|---|---|---|
| WIP-1 | **Source Analytics becomes a tab in the Sources editor** | Design: artifact "Source Analytics Tab" (claude.ai/artifact/BQDrAD5y7bKoaZG7Dp3fMV), Q1–Q12, rendered on the owner's library. The owner proposed the tab; the separate `SourceAnalyticsView` and the Analyze button go. Sections: Only here · Shared with your other sources · Playback · Connections · Server addresses · Catalogue & guide · Unrecognized prefixes. Today's four queries take ~60 s on the owner's library (fingerprint 15.6 s, overlap 24.8 s, unique 5.9 s, prefixes 14.2 s); overlap and unique compare lowercased **live-only** names (`repositories/analytics.py:107–220`) instead of `content_key` — on `COALESCE(content_key,'id:'\|\|id)` all three media types took 2 s. Build order: (1) the tab from stored data; (2) a `playback_events` table (outcome, HTTP code, time to picture, seconds watched — none stored today, log only); (3) connection hold time: on a 458/509 refusal while MetaTV holds no stream, poll the account endpoint (`active_cons`, no stream slot used) every 30 s, auto-start when free, record the hold (TREX measured by hand: ~22 min) → "usually frees up within …"; (4) failures by time of day once data exists. Supersedes "Sources, Refit" §5 Q17–Q19, never built. |
| WIP-2 | **Sources editor still clips at common widths** | "Sources, Refit" (claude.ai/artifact/56U1W8kTcxySywtWF6tDoQ) Q1–Q16 are unanswered except Q10 (Add Source in the editor, shipped #963). Rendered 2026-10-20 at 1600 px: the action row and Account Info still clip ("Refresh Guid…", "Refresh A…"). WIP-1's tab inherits this space. |
| WIP-3 | **Exclusions dialog** | Open questions: add a Genre section; replace "Content Types" (a hand-typed list, 7 groups / 28 exact provider category names) with tag-based Channel Categories (live counts: Sports 8,758 · News 738 · Music 683 · Kids 623 · 24/7 208 · Adult 184 · Religious 33); make every section collapsible with remembered state; does excluding a genre hide a title carrying *any* excluded genre?; one row per country (Chile and Colombia appear twice). |
| WIP-4 | **Onboarding, remaining** (branch `onboarding`, not main) | Owner-approved: R5 persistent no-sources notification, wording per cause incl. all-disabled; R6 five empty states, kept simple; R7 one line pointing at the Exclusions chip in the new-regions prompt plus a chip pulse; the clipped "Sourc" label; a re-runnable tour from the Tools menu, later. Design: artifact "First Run" round 2 (claude.ai/artifact/N2dC3RFFxojzxXJPv8Meh1). |
| WIP-5 | **Deferred by the owner** | Genre subgenres (Cooking, Travel, Religious… stay unfolded until a subgenre model exists) and per-language genre aliases — memory `project_genre_subgenres_and_translations`; compiled builds (Nuitka parked on branch `nuitka-builds`, standalone refuses PyQt6 on macOS; next try PyInstaller + a Nuitka-compiled `metatv` module); downloads & recordings rework (design pass first). |
| WIP-6 | **Shortened titles in the sidebar don't show the full title on hover** (owner, 2026-10-21, seen in Recommended) | Not a design question — a bug to fix later. Cause: `chip_row.build_chip_row` makes the whole row `WA_TransparentForMouseEvents` when it has no trailing button (`gui/chip_row.py:641–642`), so the eliding title label's own full-title tooltip (`chip_row.py:187/192`) never receives the hover; the `QListWidgetItem` underneath answers instead, and in Recommended its tooltip is only reason · rating · genres (`gui/sidebar/recommended.py:245–248`), with no title. Fix at the shared row, not per section: the row is transparent on purpose (the list item keeps selection and clicks, `chip_row.py:449–454`), so have each host put the full title as the first line of the item tooltip — better, one helper next to `build_chip_row` that every caller uses (Recommended, History, Favorites, Queue, Watch Alerts, transfers: `grep -rln "build_chip_row(" metatv/gui`). Check each of those sections, not just Recommended. Test: an elided title's item tooltip contains the full title. |

## Needs investigation first

| # | What | Known so far |
|---|---|---|
| D57 | GUARD-4 matches stored fields by bare name | False "wired" across models; false "unwired" through `setattr` (#912). Needs type resolution. |
| D60 | State changes not reaching on-screen surfaces — reader half | Owner-requested audit: every watch/queue/alert/favourite surface repaints on change. Writer half is guarded. |
| D61 | Pre-play probe spends the only connection on one-slot sources | Skip it when `max_connections == 1` and no alternate URL; measure on the owner's account first. |
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
| F55 | **Class:** SQL case-insensitive matching folds ASCII only — `lower()`, `LIKE` and `.ilike()` leave `Ş`, `É`, `Ö`… untouched, so any comparison against Python's `lower()`/`casefold()`, or a lowercase search term, misses a non-ASCII capital | Confirmed: `lower('ÉCOLE')` = `École`; `'Şaşmaz' LIKE '%şaşmaz%'` = 0. **Census (2026-10-19):** 20,306 channel titles and 1,660 tags carry a non-ASCII capital; sites = 24 `.ilike(` calls in 11 files (`watchlist_matching`, `epg_watchlist`, `filter_utils`, `search_ranking`, `channel_lens`, `channel`, `epg`, `tag_facet_query`, `main_window_metadata`, two scripts) + `func.lower` at `search_ranking.py` (`_word_padded`, two title rankers) and `tag.py` tag search. Visible effect: searching "école" misses "ÉCOLE". One instance already crashed: the tag lookup (#932, below). Fix options: register a Python casefold SQL function on connect (loses index use on those predicates), or store a casefolded search field at ingestion (compute-once; needs a column + migration). |
| F56 | **Compromise from #932 (tag lookup):** the fix matches the exact stored value OR the ASCII-lowered one, which ends the crash but does not fold non-ASCII case | Two spellings differing only in a non-ASCII capital ("ŞAŞMAZ" / "Şaşmaz") would still become two tags. Census 2026-10-19: 0 such pairs among all tags. Closes with F55's real fold. |
| F59 | **Class:** production companies stored as `person` tags ("Amblin Entertainment", "Marvel Entertainment") | Census 2026-10-20 on the owner's library: **3,248** person tags / **7,483** links whose value contains Entertainment, Pictures, Productions, Studios, Films, Media, Ltd, Inc., GmbH or Company. Likely the credits feeder taking TMDb production companies into the person facet. Found while reviewing genre tags; not touched.
| F60 | Channel rows belong to sources that no longer exist | Found 2026-10-20: ~50 rows under three provider ids absent from `providers` (`38497d8e…`, `3ae8ea40…`, `41241966…`). FKs are off, so provider delete must prune every child table by hand; find which path skipped `channels`, then sweep the orphans. |
| F61 | Qt `Aborted` on macOS CI in `test_qa_checklist_navigation.py` | #973's run, macos-14 shard 3/4: abort while `qa_checklist_window.run` → `_resolve_base_url` → `build_info.git` waited on a subprocess. Passed on the next run; unrelated to #973. Watch for a repeat before digging. |

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
- **F57** — rolling builds skip the test suite (#931). It was 48 of the macOS job's 54 minutes and every newer push cancelled it, so no `.dmg` finished on a busy day. Cost: with merges skipping checks (the working plan), a rolling build can publish from a `main` CI later reports red; the launch smoke test still runs on every build, and `v*` tag releases still run the full suite.
- **F58** — parser compromises from #929 (measured on 787,006 names): 4 person tags become collections ("Cheech And Chong", "Jay And Silent Bob" — duo names the collection recogniser claims first); "FRANKENSTEIN" after "(MULTI SUB)" stays a credit (owner: likely a one-off); the late quality pass (step 6d) is dropped whole when it finds a tier word, because there the word is a title ("One Piece Film Gold", "STC PPV"), so a quality beside such a word stays in the title (not measured); a quality named after the year ranks after every other quality source.
