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

Nothing. (D69 — measured audio missing from the collapse election and EPG On now —
closed with a guard by its PR; WIP-6 — full title on hover — closed by its PR.)

## Work in progress — designed, waiting on the owner's answers

Nothing here is built. Each row is a design or a set of open questions; build only after
the owner answers. Recorded 2026-10-21.

| # | What | Where it stands |
|---|---|---|
| WIP-1 | **Source Analytics becomes a tab in the Sources editor** | Design: artifact "Source Analytics Tab" (claude.ai/artifact/BQDrAD5y7bKoaZG7Dp3fMV), Q1–Q12, rendered on the owner's library. The owner proposed the tab; the separate `SourceAnalyticsView` and the Analyze button go. Sections: Only here · Shared with your other sources · Playback · Connections · Server addresses · Catalogue & guide · Unrecognized prefixes. Today's four queries take ~60 s on the owner's library (fingerprint 15.6 s, overlap 24.8 s, unique 5.9 s, prefixes 14.2 s); overlap and unique compare lowercased **live-only** names (`repositories/analytics.py:107–220`) instead of `content_key` — on `COALESCE(content_key,'id:'\|\|id)` all three media types took 2 s. Build order: (1) the tab from stored data; (2) a `playback_events` table (outcome, HTTP code, time to picture, seconds watched — none stored today, log only); (3) connection hold time: on a 458/509 refusal while MetaTV holds no stream, poll the account endpoint (`active_cons`, no stream slot used) every 30 s, auto-start when free, record the hold (TREX measured by hand: ~22 min) → "usually frees up within …"; (4) failures by time of day once data exists. Supersedes "Sources, Refit" §5 Q17–Q19, never built. **Answered 2026-10-31: every recommendation accepted** — Q1–Q10 and Q12 yes, Q11 (time of day) later once data exists. Build order: (1) editor clipping (WIP-2, done), (2) the tab from stored data (done 2026-10-31: Only here + Browse, Shared + redundancy hint, Catalogue & guide, Server addresses, Prefixes; old view + Analyze removed), (3) `playback_events` + Playback (done 2026-10-31: recorded at the start-watch verdicts, `playback_weekly` fold task, Playback section), (4) hold-time wait + Connections (done 2026-10-31: `gui/connection_wait.py`, `connection_holds` table, Connections section). (5) Q11 time of day (done 2026-10-31: `gui/hour_strip.py`, per-local-hour counts on `PlaybackSummaryDTO.by_hour`, drawn once 30 plays exist). All steps done. |
| WIP-2 | **Sources editor clipping — FIXED 2026-10-31** | Minimums made honest instead of the "Sources, Refit" relayout: action bar and footer wrap (`FlowLayout(align_right=True)`), Account Info pairs wrap, the URL group's 85-char title became a hint, forms stack when narrow, the tab scroll areas report their content width (`_VerticalScroll`). Editor minimum 542 → ~340. Refit Q1–Q16 otherwise still unanswered; its Q2 (tabs → one page) is superseded by Analytics-as-a-tab (WIP-1). |
| WIP-3 | **Exclusions dialog** | Open questions: add a Genre section; replace "Content Types" (a hand-typed list, 7 groups / 28 exact provider category names) with tag-based Channel Categories (live counts: Sports 8,758 · News 738 · Music 683 · Kids 623 · 24/7 208 · Adult 184 · Religious 33); make every section collapsible with remembered state; does excluding a genre hide a title carrying *any* excluded genre?; one row per country (Chile and Colombia appear twice). |
| WIP-4 | **Onboarding, remaining** (branch `onboarding`, not main) | Owner-approved: R5 persistent no-sources notification, wording per cause incl. all-disabled; R6 five empty states, kept simple; R7 one line pointing at the Exclusions chip in the new-regions prompt plus a chip pulse; the clipped "Sourc" label; a re-runnable tour from the Tools menu, later. Design: artifact "First Run" round 2 (claude.ai/artifact/N2dC3RFFxojzxXJPv8Meh1). |
| WIP-5 | **Deferred by the owner** | Genre subgenres (Cooking, Travel, Religious… stay unfolded until a subgenre model exists) and per-language genre aliases — memory `project_genre_subgenres_and_translations`; compiled builds (Nuitka parked on branch `nuitka-builds`, standalone refuses PyQt6 on macOS; next try PyInstaller + a Nuitka-compiled `metatv` module); downloads & recordings rework (design pass first). |

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
| GUARD-7 | PyQt segfaults at interpreter exit — CAUSE FOUND 2026-11-01 | gdb: `cleanup_on_exit` (PyQt's atexit) → `sip_api_visit_wrappers` → `cleanup_qobject` → `sip_api_get_address` on a freed wrapper. A live, Python-owned top-level window is deleted inside that walk and frees its children's wrappers mid-iteration; the chance grows with the widget count (#991's tiles: 0 → 12 of 16 window boots under load on 3.12; CI red twice in `test_search_view_top_gap`). Releasing the window first (`gui/app_exit.release_before_exit`, called by `main()` and the window-booting test children): 0 of 24. `sip.setdestroyonexit` does not exist in PyQt6. Still open: `test_mainwindow_launch_smoke` keeps its `os._exit(0)` workaround — switch it to the release once CI has shown the fix holds. |
| F55 | **Class:** SQL case-insensitive matching folds ASCII only — `lower()`, `LIKE` and `.ilike()` leave `Ş`, `É`, `Ö`… untouched, so any comparison against Python's `lower()`/`casefold()`, or a lowercase search term, misses a non-ASCII capital | Confirmed: `lower('ÉCOLE')` = `École`; `'Şaşmaz' LIKE '%şaşmaz%'` = 0. **Census (2026-10-19):** 20,306 channel titles and 1,660 tags carry a non-ASCII capital; sites = 24 `.ilike(` calls in 11 files (`watchlist_matching`, `epg_watchlist`, `filter_utils`, `search_ranking`, `channel_lens`, `channel`, `epg`, `tag_facet_query`, `main_window_metadata`, two scripts) + `func.lower` at `search_ranking.py` (`_word_padded`, two title rankers) and `tag.py` tag search. Visible effect: searching "école" misses "ÉCOLE". One instance already crashed: the tag lookup (#932, below). Fix options: register a Python casefold SQL function on connect (loses index use on those predicates), or store a casefolded search field at ingestion (compute-once; needs a column + migration). |
| F56 | **Compromise from #932 (tag lookup):** the fix matches the exact stored value OR the ASCII-lowered one, which ends the crash but does not fold non-ASCII case | Two spellings differing only in a non-ASCII capital ("ŞAŞMAZ" / "Şaşmaz") would still become two tags. Census 2026-10-19: 0 such pairs among all tags. Closes with F55's real fold. |
| F59 | **Class:** production companies stored as `person` tags ("Amblin Entertainment", "Marvel Entertainment") | Census 2026-10-20 on the owner's library: **3,248** person tags / **7,483** links whose value contains Entertainment, Pictures, Productions, Studios, Films, Media, Ltd, Inc., GmbH or Company. Likely the credits feeder taking TMDb production companies into the person facet. Found while reviewing genre tags; not touched.
| F60 | Channel rows belong to sources that no longer exist | Found 2026-10-20: ~50 rows under three provider ids absent from `providers` (`38497d8e…`, `3ae8ea40…`, `41241966…`). FKs are off, so provider delete must prune every child table by hand; find which path skipped `channels`, then sweep the orphans. |
| F61 | Qt `Aborted` on macOS CI in `test_qa_checklist_navigation.py` | #973's run, macos-14 shard 3/4: abort while `qa_checklist_window.run` → `_resolve_base_url` → `build_info.git` waited on a subprocess. Passed on the next run; unrelated to #973. Watch for a repeat before digging. |
| F62 | `ProviderItemWidget` (`sidebar/sources.py`) is no longer used in production at all | Since 2026-10-31 the Sources manager shows chips (`_SourceChip`), not rows, so neither branch of `ProviderItemWidget` is built by the app; only `test_provider_toggle_busy.py` and `test_epg_indicator.py` construct it. Its `show_actions=True` branch also carries an Analyze button whose `analyzeClicked` nothing listens to. Delete the class with those two tests (owner call — they guard behaviour the editor's action bar now owns). The status-dot rule it shared is `subscription_status.source_status_dot`. |
| F63 | A source's guide feed reaches only one channel per guide id | Re-measured 2026-11-01 (Shark since deleted). **Fixed (#994):** tier 1 of `epg_matching.build_match_map` gave a shared exact id to whichever row came back last — 60 of TREX's feed ids went to ProSat (expired) and 1 to a deleted source; it now skips hidden sources and prefers the feed's own (TREX links 490 → 536). **Open — owner's call:** the map is one feed channel → one library row, and every guide read keys on `channel_db_id` (10 sites incl. the watchlist join), so a source's HD/SD/RAW variants sharing an id get one guide between them: 738 TREX live channels carry an id in TREX's feed, 371 have guide rows. Fix shape: read a channel's guide as its own source's feed rows for its `epg_channel_id`. Ceiling either way: 9,192 TREX channels have an id, the feed covers 714. |
| F64 | Intermittent segfault in ubuntu CI shard 1 — OPEN, parked 2026-10-31 | Recurred after #984 (two ubuntu shards). Reproduces locally ~1 run in 3: CI shard 1's 182 files in CI order, `-p no:randomly`, Python 3.12 venv (`PYTHON=~/.cache/metatv-py312/venv/bin/python`). Crash site: `tests/test_view_chip_hover.py` → `theme.apply_theme` → `_reapply_registered_styles` → `setStyleSheet` → `setPalette` → `invalidateGraphicsEffectsRecursively` → `QWidget::graphicsEffect` on a child whose d_ptr is garbage (0x1121): a FREED widget still in its parent's C++ child list. One variant aborted in sip `sipOMAddObject`/`add_aliases` (heap corruption). All other threads idle in QThreadPool waits → main-thread corruption. Ruled out: (1) #980's viewport event filter — replacing it with item ToolTipRole writes still crashed on try 3 (the earlier 4/4 pass was chance, ~20% at a 1/3 rate); (2) the theme registry holding Qt-deleted children — PyQt6 marks a C++-deleted viewport `sip.isdeleted` True, so the sweep's RuntimeError guard already covers it. Next step needs ASan/valgrind or a debug Qt to find who frees the widget without unparenting it; ≥8 serial passes before calling any fix proven. Same family as F61/GUARD-7. |
| F65 | The title-identity key `COALESCE(content_key, 'id:' \|\| id)` is rebuilt at every collapse site | Found adding Analytics' viewing/region counts, 2026-10-31 (which added one more, `analytics.py` `_TITLE_KEY`). SQL copies: `platform_shelves.py:88`, `tag_facet_query.py:301` and `:429`, `channel.py:578`, `analytics.py:34`, raw SQL in `migrations/person_aliases.py:111`. Python copies: `preference_engine._title_key` (:220), `discovery_engine.py:192`, `:215`, `:885`. Pure duplicates of one rule (CLAUDE.md "Content identity"); they differ only in which columns they read (`ChannelDB` vs a subquery's `inner.c`, or a card's `channel_id`). Fix: `content_identity.title_key_expr(content_key_col, id_col)` for SQL and `title_key(content_key, id)` for Python, every site routed through them. |

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
