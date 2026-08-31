# MetaTV — Refactor, Dedup & Best-Practices Plan

**Audience:** an implementing agent (Sonnet).
**Source:** full-codebase review on 2026-06-01 (main @ d194dad, 94 files / ~32k LOC).
**Goal:** fix best-practice violations, remove duplication, and break up oversized
files — without changing user-visible behavior except where a task explicitly fixes a bug.

## Ground rules for the implementer

1. **Follow `CLAUDE.md` critical rules.** Several tasks below exist *because* a rule
   was violated. Do not introduce new violations while fixing old ones.
2. **Small commits, one task per commit.** Each task lists its own acceptance check.
3. **Run the test suite after every task:** `venv/bin/python -m pytest tests/ -x -q`.
   All must pass. If a task changes behavior, add/adjust a test.
4. **No behavior change unless the task says so.** P0 tasks fix real bugs; everything
   else must be a pure refactor (same runtime behavior, smaller/cleaner code).
5. Work top-down: P0 → P1 → P2 → P3. Stop and report if any task's premise no longer
   matches the code (it may have been fixed since this plan was written).

---

## Running duplication ledger (append as found)

Started 2026-08-26. The rule the owner set: **every duplicate found gets fixed
or flagged here — never dropped.** These are found incidentally while building
something else, which is exactly why they need a written home; the alternative
is rediscovering the same three "in N minutes" formatters next quarter.

Each entry says where the copies are, what actually differs (a pure duplicate
and a policy difference need different fixes), and whether it is done.

### DONE

| # | What was duplicated | Copies | Resolution |
|---|---|---|---|
| D1 | Quality token → colour | `chip_roles.SIDEBAR_CHIP_QUALITY` painted every tier one flat `COLOR_WARN`, while `badge_utils` has owned the per-tier map since #257 | `badge_utils.quality_outline_color()` made public; the sidebar chip reads it; the orphaned role deleted (#462) |
| D2 | Sub-group headings | THREE mechanisms in one section: styled `QTreeWidgetItem`s (EPG), and two em-dash divider rows in the VOD list that looked identical but behaved differently | `GroupHeading` widget in `sidebar/base.py`; all four Watch Alerts groups use it (#463) |
| D3 | Programme progress bar | TWO painters that did not match — `epg_widgets` delegate (`QColor(55,55,55)` + HSV ramp) and `epg_agenda_widget` (`QColor(60,60,60)` + flat amber) — plus 4 hardcoded colour literals | `gui/progress_paint.py` — one `paint_progress()`, token-coloured; both migrated, Watch Alerts rows are the third caller |
| D4 | Watch Alerts row construction | `sidebar/alerts_rows.py` hand-assembled a QHBoxLayout while History, Favorites, Queue and Recommended all used `chip_row.build_chip_row()` — with its own chip builder (`_chip`, applied via `setStyleSheet`, so it went STALE on a theme switch), its own quality sheet duplicating `_quality_chip_style` value-for-value, and its own `news_chip_sheet` | Both rows are shells over `build_chip_row`; the builder gained `leading_slot` / `title_chips` / `title_suffix` / `tail_widget` / `indent` and a `CHIP_NEWS` kind, so the variants are IN the shared core rather than a trimmed copy. Titles middle-elide for the first time |
| D5 | Three methods defined twice in `alerts.py` | `_toggle_series_group`, `_toggle_keyword_group`, `_add_group_heading` — a verbatim 42-line block at two places (identical MD5). The second definition silently won; the first was unreachable | Dead copy deleted. Found by listing method spans while planning the file split — nothing else would have surfaced it, since Python accepts it silently |
| D6 | `VOD_ALERT_*` theme roles | `VOD_ALERT_NAME` and `VOD_ALERT_COUNT_IDLE` were BYTE-IDENTICAL (`"color: <COLOR_TEXT>;"`), and a test asserting a count chip's sheet was silently satisfied by the row's NAME label | All three orphaned by D4 and deleted; the test now asserts the absence it is named for |
| D7 | `sidebar/base.py` over the 1000-line cap (was F11) | `metatv/gui/sidebar/base.py` | 1319 lines. The pressure pass — `_content_height`, `resizeEvent` and the height limits — moved to `sidebar/section_cap.py` as `SectionContentCapMixin`, mixed in beside `RowBudgetMixin`, which is the same shape: a cross-cutting behaviour reaching the section's widgets through `self` and owning none of them. (It moved out as `section_pressure.py`/`SectionPressureMixin` and shed the fold half entirely a day later — see UI_UX_GUIDELINES, "Scrolling, rather than folding".) base.py was ~1210 immediately after the move and is **1408** today — the split bought room that later work spent, and it has now been written into `tests/code_health_baseline.json` by a rebaseline rather than shrunk. **That entry is a receipt, not an absolution**: the flat 1000-line cap for new files is what it failed, and the next two cohesive units to lift out are still the header builders and the splitter arithmetic (`_grow_in_splitter` / `_release_in_splitter` / `_floor_of`), neither of which is about what a SECTION is. **Still over the cap** — the header builders and the splitter arithmetic (`_grow_in_splitter` / `_release_in_splitter` / `_floor_of`) are the next two cohesive units, and neither is about what a SECTION is. Watch the MRO when moving a Qt override: `resizeEvent` now resolves to `RowBudgetMixin`'s, which reaches the pressure one only because it calls `super()`. |
| D8 | Same-rank quality collapse | THREE inline copies in `channel_name_utils.py` — `_strip_attributes`, the tail of `parse_channel_name`, and the new scene pass. Two spelled the accumulator `seen_ranks` and one `_seen_ranks`, so a search for the duplicate found two of the three | `_collapse_same_rank()`; all three call it. `test_the_same_rank_collapse_has_exactly_one_implementation` guards the IDENTIFIER, not the behaviour — behaviour is what a fourth copy would also get right on the day it was written |
| D9 | The details-pane action-button wiring | Four test files each hand-wrote the eleven-keyword `set_action_buttons(...)` call, so adding a twelfth button broke four files at once and the fix was the same edit copied four times | `tests/conftest.wire_details_action_buttons()`; all four call it. The same enumeration failure CLAUDE.md names, in test clothing, and the same answer — one shared factory |
| D10 | Per-field `raw_data` → `MetadataDB` backfills | `runtime_backfill.py` (#588) was about to be joined by a near-identical `trailer_backfill.py`: same keyset loop, same IS-NULL filter, same registration, one column different | Generalised to `raw_field_backfill.py` with a `FIELDS = {column: resolver}` table. A third field is one row and a version bump, not a 23rd migration module and a 23rd hand-written registration (which is ledger F29). `test_every_resolver_is_the_one_ingestion_uses` asserts the table holds the SAME function objects ingestion calls, so a field cannot drift between the two paths |
| D11 | `DETAIL_QUEUE_BTN` named for one of its two users | `theme.py` + `details_actions.py` | The Trailer button wants the identical tier-2 sheet. Renamed to `DETAIL_SECONDARY_BTN` — named for the ROW — in the same edit, because CLAUDE.md's rule is that a sheet used by >1 widget is a shared role, and a role named after one widget is exactly how the second copy gets pasted |
| D12 | The sports/events `special_view` filter | FOUR hand-written copies in `channel_stats.py` — `get_sports_channels`, `get_events_channels`, `get_sports_taxonomy`, `get_sports_counts` — each repeating `special_view == X` + `is_hidden == False` + non-NULL stream_url + `NOT LIKE '#%'` | One `_special_content_query(view, scope, *columns)`. **Not a cosmetic dedup**: none of the four excluded a hidden provider, and 16,715 of the owner's 35,181 sports rows belong to a source that is `is_active = 0`. The exclusions now come from `VisibilityScope` and `scope` is a REQUIRED argument — there were no callers, so making it impossible to forget cost nothing, and forgetting is exactly how the gap existed. `test_the_filter_has_exactly_one_definition` counts the copies |
| D13 | The view-switcher chip list — THREE copies | `app_header._create_nav_group` built the chips from a local `specs` list; `main_window_nav._deactivate_view_chips` kept its own (`[search, epg, prefs, discover]` plus a conditional `recipe`); and `tests/test_nav_segmented_track_layout.py`'s child process kept a third | One module-level `NAV_CHIP_SPECS`, read by all three. **Two silent failure modes and one misleading one**: a chip missing from the deactivator stays LIT while another view is showing, and a stale list in the layout test measures five cells against a six-cell track — which reads as a layout regression rather than a stale list. CI found the third copy after the local run missed it, because the file mentions none of the strings a grep-derived file list would match |
| D14 | `_hide_all_content_views` carried TWO enumerations of the same views | `main_window_nav.py` — one hand-written sequence of `if visible: view.on_deactivate()` and a separate hand-written sequence of `view.setVisible(False)`, each with its own `in self.__dict__` guards | One `CONTENT_VIEW_ATTRS` tuple, iterated once for both. **Found by walking into it**: I added the Sports view to the deactivation half and not the hiding half, and it stayed VISIBLE behind the next view with nothing raising. `getattr(view, "on_deactivate", None)` is polymorphism, not a defensive hasattr — the list genuinely mixes ContentViews with a QTreeView. The lazily-built explore_views live in a dict, so they keep their own loop |
| D15 | Two views over the dated `special_view` rows | `ppv_view.py` (230 lines, zero importers) vs the new `events_view.py` | `ppv_view.py` deleted. It was not merely unreachable, it was unshippable: it queried on the UI thread, stored ORM rows in cards and read them on a 1 Hz timer after the session closed, emitted a `ChannelDB` across a signal, and excluded no hidden provider. The countdown was the good part and it moved to `relative_time.humanize_countdown`, beside the two forward formatters that already lived there. `test_ppv_view_is_gone` fails if it returns |
| D16 | Five unbounded `DELETE`s on `epg_programmes` | `epg_manager.py` ×3 (guide clear before import, `purge_provider_epg`, `prune_expired`), `repositories/epg.py` `clear_provider_data`, and `repositories/channel.py` `prune_provider_content` ×2 | Four routed through one `delete_programmes_chunked()`; the fifth (`epg_by_channel`) is **not a pure duplicate** and was exempted in place: it is one step of an atomic cascade whose correlated doomed-set subquery only resolves while the channel rows still exist, so committing per chunk would publish a half-pruned tree. **Measured, not guessed**: the guide clear held SQLite's single write lock 69.3s against a 30s `busy_timeout` — chunking cut worst hold to 0.90s AND total to 43.4s. The two `channel.py` copies were invisible to a grep scoped to the EPG files; the AST guard in `tests/test_epg_delete_chunking.py` found them |

### FLAGGED — not yet done

| # | What | Where | Why not done yet |
|---|---|---|---|
| F1 | `style_group_heading` vs `GroupHeading` | `sidebar/favorites.py:180`, `sidebar/queue.py:721` | Mechanical, but touches two sections outside the Watch Alerts slice. Migrate, then **delete `style_group_heading`**. Owner asked for this explicitly. |
| F2 | Forward relative-time strings | `relative_time.humanize_until` (new) vs `epg_watchlist_mixin.py:750` | **Not a pure duplicate — a policy difference.** The mixin switches to a clock time at 120 min (the shared one at 60), says `"in N min"` not `"in Nm"`, and renders `"Today 2:44 PM"` / `"Wed 2:44 PM"`. Unifying means choosing one wording and changing how the EPG watchlist looks, which is a design call on a surface not yet reviewed. |
| F3 | `_remaining_str` | Defined in `epg_agenda_widget.py:18`, imported by `epg_watchlist_mixin` | Already single-definition, just living in the wrong module — it belongs beside `humanize_remaining` in `relative_time.py`. Safe pure move. |
| F4 | Region alpha-3 gaps | `channel_name_utils.REGION_FULL_NAMES` | `DNK` was missing while `DEN` (the IOC/FIFA code) was present, so real provider data matched nothing. Only `DNK` was added — **the table likely has other ISO-vs-IOC pairs with the same gap** and deserves one systematic pass rather than a fix per owner report. |
| F10 | **Quality chips sit in a different place in different sections** | `chip_row` callers | V3 settled that a quality token travels WITH the title in Watch Alerts (owner: "the quality chip should be align left right after the channel title") — it is a claim about that copy. History and Recommended still put theirs in the right-hand rail with the year and language. `title_chips` now makes either possible, so this is purely a design question: should the Watch Alerts rule apply everywhere? NOT applied unilaterally — moving a chip across every sidebar list is a look change the owner has not reviewed. |
| F14 | **A fourth sub-group heading mechanism** | `epg_watchlist_mixin.py:794` `_make_quiet_section` | The EPG watchlist VIEW draws its "OFF AIR · N" fold with a flat `QPushButton` whose label carries a `move_down_icon`/`move_up_icon` glyph — a caret-as-text toggle, which is exactly the affordance `GroupHeading` dropped in #329, plus a composed inline stylesheet. Found while adding the sidebar's "Upcoming" group. **Not a pure duplicate:** it is a different surface with a different concept ("no matches at all" vs "airing later"), and `GroupHeading` is sidebar-shaped. Unifying is a look change to the EPG view, which the owner has not reviewed. |
| F15 | **Two row-height rules, now one** | `chip_row.row_min_height` | RESOLVED here, logged because the shape recurs: Watch Alerts derived its row floor from the font's line box, every other section summed its children, and the two agreed only below a 13px app font. A rule that lives in the one section that noticed the problem is a rule the app does not have. |
| F16 | **Chunking an oversized `IN (...)`** | `core/sql_batching.py` (new, the chokepoint) vs `provider_loader.py:401` `_CHUNK = 500` | Found while fixing the Recommended crash: `score_candidates` bound 414,759 ids into one `IN` and SQLite RAISED (`too many SQL variables`) rather than degrading. **Not a pure duplicate — `provider_loader`'s loop is correct**, it just predates the shared helper and states the size itself. The wider problem is the population: **147 `.in_()` call sites**, and nothing marks which of them can grow with the catalogue. Migrating `provider_loader` is mechanical; auditing the other 145 is a real pass and needs a way to tell "bounded by user data" from "bounded by the library". |
| F17 | **RESOLVED, and one of its two claims was wrong** | `tag.py` `_build_collapsed_sample_query` | **Claim 1 (own quality ladder) was right and is fixed.** The local CASE disagreed with `QUALITY_TIER_RANK` on ORDERING: HDR ranked above HD (canonical puts it at the default, BELOW HD, because it is a dynamic-range descriptor and not a resolution tier — the table says so), 8K tied with 4K, SD tied with LQ. A title with an HD copy and an HDR copy elected differently in the channel list and in Discover. A **third** ladder, `_QUALITY_RANK_CASE`, was found dead with no callers and deleted before someone adopted it. **Claim 2 (no exclusion penalty) was WRONG — mine, not an auditor's.** `tag.py` applies exclusions in `_faceted_channel_id_query` BEFORE the collapse, so an excluded variant never enters the group and cannot be elected. That is structurally different from `channel.py`, which applies them in Python AFTER and therefore genuinely needs the penalty. Verified by reading the call path rather than assuming the two collapses were the same shape. |
| F18 | **An exception escaping a Qt slot ABORTS the app, and 44 sites can do it** | `main_window_series.py:play_episode` (fixed) + 43 more `try/finally`-with-no-`except` blocks touching a session across `gui/` | PyQt calls `qFatal()` on an unhandled exception in a slot: no traceback from Qt, no recovery, process gone. The owner hit it live — `database is locked` on `UPDATE episodes SET last_played` during a 293,468-item refresh, ending in `SIGABRT`. Fixed at the one site that crashed; **the shape exists at 43 others** (derived by AST, listed in the PR). **Not fixed wholesale on purpose:** the real chokepoint would be a global `sys.excepthook` that logs instead of aborting, and that is a design call with a real downside — it converts every unhandled bug into a silent log line. Owner's call. The narrow rule that IS safe to state now: *bookkeeping must never be able to prevent playback*, and a `try/finally` with no `except` around a write in a slot is a latent abort. |
| F19 | **A bulk catalogue insert holds the write lock past every timeout** | `provider_loader.load_provider` | Confirms audit finding A4 ("retry-on-lock is insufficient under real contention") with live evidence: one refresh inserting 293,468 rows starved `persist_url_stats`, `series_monitor`, `_bg_mark_played` and `episodes.mark_played` simultaneously, all failing `database is locked` against a **30 s** `busy_timeout`, and the load itself then failed the same way. Raising the timeout is not the fix — a big enough insert beats any value. The fix is to stop holding one lock that long (chunked commits with yields between), which changes crash-safety semantics for a half-written catalogue and therefore needs deciding, not patching. |
| F32 | **Episode labels the marker pass leaves behind** | `channel_name_utils` `_extract_episode_marker` | After SxxExx is lifted out, 8 rows still read "Konusanlar 77 Bolum" — *bölüm* is Turkish for episode, and the number duplicates the detected_episode now stored beside it. 28 more read "Konusanlar EXXEN", a platform tag left in the title. **Not done because both are guesses in a language-specific vocabulary**: `bolum` could be part of a real title, and a platform tag needs the same curated list `detected_collection` already owns. 36 rows total against a 960-row win — worth doing as part of a collection/platform-token pass, not inside a parser slice. |
| F29 | **Migration tasks are registered by a hand-listed enumeration in `main_window.py`** | `metatv/gui/main_window.py` — 21 `self.migration_manager.register(...)` calls, each with its own `from ... import` line | Exactly the shape CLAUDE.md names as the project's recurring bug: *an enumeration never sees what nobody remembered to add*. A task file can exist, be correct, be tested, and never run, and nothing fails — which is why `test_runtime_backfill.py` has to assert its own registration by grepping `main_window.py` source, a test no other backfill has. Sibling `metatv/whats_new/` already solved this: `_load_entries()` discovers `entries/*.py` with `pkgutil.iter_modules`, and `test_entry_files_match_loaded_entries` fails when a file does not produce a loaded object — a guard that caught a real broken entry in this very slice. **Not done here because ORDER may matter**: the registrations are currently in a fixed sequence and nothing declares whether any task depends on an earlier one, so auto-discovery needs each task to state its own ordering (an `after` field or a sort key) before the list can be deleted. That is a decision, not a mechanical move. Payoff: ~40 lines off the largest file in the tree, and registering a migration stops being a step anyone can forget. |
| F30 | **`channel_name_utils.py` is 3,331 lines and doing six jobs** | `metatv/core/channel_name_utils.py` | Region tables, quality/encoding/audio vocabularies, the parser itself, tag helpers, AI-provenance detection, sports keywords and EPG TLD helpers all live in one file. The scene-release pass added 209 lines and the ratchet was re-baselined rather than the file split — **a receipt, not an absolution.** The cohesive unit to lift out is the scene pass (`_SCENE_*`, `_canonical_audio_codec`, `_sub_outside_brackets`, `_extract_scene_release`) into `core/scene_release.py`: it is self-contained and called from exactly one place. **The blocker is direction.** The parser must call the pass, so `scene_release` may not import `channel_name_utils` — yet it needs `RESOLUTION_TO_QUALITY`, `ENCODING_NORM`, `AUDIO_CODEC_NORM`, `_SOURCE_QUALITY_NORM`, `_Attributes` and `_collapse_same_rank`. The one-way shape is a third module holding the vocabulary that both import, which means moving `QUALITY_TIER_RANK` — **7 external importers**, and CLAUDE.md's rule says each must then import from the defining module, not a re-export. That is a decision about who owns the ladder, not a mechanical move, so it was not taken inside a parser slice. |
| F31 | **Three sport-keyword lists — a POLICY difference, not a duplicate. Half fixed** | `channel_name_utils._sports_keywords_flat()` (102 keywords, curated league/team data) vs `special_content.SPORTS_GATE_STEMS` + `SPORTS_GATE_TOKENS` (the gate) vs `parse_ppv_event`'s own map | **What was fixed:** the gate's single list became two named ones, because a keyword's matching rule is a per-keyword DECISION and was being inferred from the call site. `sport` must reach SPORTSNET, `moto` must reach MOTOGP; `bein` must not reach "being", `f1` must not reach TF1. Applying one rule to the whole list either way is wrong — measured, whole-token matching for all of them removed **11,451 real sports channels** from the view, an order of magnitude more damage than the false positives it was meant to fix. `parse_ppv_event` got the same split. **What is still open:** the gate's vocabulary and the curated league data are still two literals in two modules, and the ten keywords the gate holds alone (`espn`, `bein`, `sky sports`, `fox sports`, `tsn`, `nbc sports`, `sport`, `fight`, `racing`, `moto`) are broadcaster brands and generic words that belong nowhere near league ASSIGNMENT. That separation is correct and undeclared — which is exactly how someone "tidies" them together. One curated home, three named views. |
| F20 | **Selection→metadata fetch is undebounced** (audit F9, magnitude now stale) | `main_window_metadata.py:442` `on_channel_selection_changed`, `:530` `executor.submit` | F9 framed this as "the stutter convoy" and sized it off F1+F2 — ~13 s of query work per filter click. **Both are fixed** (#547 took the collapse 8.3 s → 1.6 s, #541 removed the 6.5 s no-op), so the convoy it was measured against no longer exists. The auditor also marked it "not independently wall-clock-measured", correctly. Re-measured on the live library: the two synchronous main-thread reads it warned about are **0.25 ms median, 0.40 ms p95 — 18 ms across 40 arrow-key presses**, i.e. never the cost, which the finding itself said. What REMAINS is real but small: holding an arrow key queues one pool job per traversed row, each creating an asyncio loop, and all but the last are discarded by the existing staleness guard. A 200 ms debounce mirroring `_search_debounce` (`main_window.py:264`) would drop ~39 of 40. **Deliberately not bundled into a batch about something else:** it touches the details pane on every selection, the most-used interaction in the app, and it is now an efficiency nicety rather than the jank fix it was written up as. Worth its own pass and its own test. |
| F21 | **`raw_data` cannot simply be deferred — a stored provider rating has to come first** (audit B9, recommendation refined) | `core/database.py` `ChannelDB.raw_data`; reader `discovery_engine.py:77` | B9 is right about the size: **386 MB measured, 36% of the 1,049 MB channels table** (the audit said "half"; it is 36%). Its recommendation — defer the column so ORM queries stop carrying it — is right for queries that never read it, and #544 did exactly that in `score_candidates` for a measured **-19.6% time, -21.8% memory**. But applying it globally would make things WORSE: `discovery_engine:77` parses the provider rating out of `raw_data` at runtime, so a deferred column turns one bulk load into an N+1 of lazy loads. **The real fix is upstream and is this project's own governing principle #2** — the provider rating is derived at read time from a blob when it should be computed once at ingestion into a stored column, the same treatment `detected_*` already gets. Store it, point discovery at the column, and `raw_data` can then be deferred everywhere rather than site by site. Needs an ingestion change plus a backfill, so it is a slice, not a patch. 56 read sites across 8 modules — worth auditing which are genuinely blob-shaped and which are fields in disguise. |
| F12 | **The code-health ratchet is red on `main`, and was before this session** | `tests/test_code_health_ratchet.py` | 7 violations at #479, 5 now — #481's split took `alerts.py` (1768) and `theme.py` off the list, F11 is the one this session made worse. The remainder (`channel_name_utils` +5, `config` +18, `main_window` +92, `main_window_streaming` +8) are long-standing. Owner's call whether to split or re-baseline; `scripts/rebaseline_code_health.py` exists for a deliberate, reviewed increase. |
| F13 | **Icon buttons built from an emoji glyph instead of a vector icon** | `sidebar/sources.py:111,160,276,286`, `sidebar/sources_strip.py:139` | `QPushButton(_icons.refresh_icon)` puts a COLOUR EMOJI in the button as text, drawn at the header's font size. In a fixed 22x20 button it is squeezed and clipped — owner, of the Watch Queue's find toggle: "it should be using the material icon and not be cropped to shit like this". That one is fixed (vector `search` key, 14px icon, matching its neighbours); these five are the same defect in the Sources section, which has its own sizing and was not in scope. Each needs a `vector_key` registered and `setIcon(resolve_icon(...))` in place of the constructor argument. |
| F6 | **Selection colours across the whole app** | every `QAbstractItemView` | `apply_list_selection()` is the chokepoint, but it APPENDS to a widget's stylesheet — so any `setStyleSheet`/`style_fn` applied afterwards silently replaces it and the view falls back to Qt's raw saturated highlight with unreadable text on it. That is exactly what happened in the sidebar (owner: "these row select colors on the midnight theme are terrible"). **Audit every item view in every theme**: confirm the selection is the theme accent, that the row text stays legible on it, and that no view has picked up a stylesheet after its selection rules. A drift guard should assert ordering — selection rules applied last, or composed — rather than trusting call order. |
| F9 | **Two `test_theme_live_refresh` tests exercise the REMOVED `refresh_theme()` sweep** | `tests/test_theme_live_refresh.py` — `TestFilterPanelRefreshTheme.test_refresh_theme_recurses_into_static_section_rows`, `TestMainWindowRefreshThemeSweepsPromotedWidgets.test_sweeps_promoted_locals_and_filter_panel` | Both fail by direct execution on `main` as well as on any branch, so they are pre-existing, not a branch regression. They assert the hand-maintained `refresh_theme()` sweep still styles widgets — the mechanism CLAUDE.md records as REPLACED by the `theme.style()` registry precisely because an enumeration could not work. A test for a deliberately removed mechanism is worse than none: it reads as coverage of live theming while guarding nothing. Rewrite against the registry or delete; the owner's call which. Sibling of F7 — both are reds the `--quick` gate never runs. |
| F7 | **`test_roles_that_declare_the_same_properties_are_reviewed` fails on `main`** | `tests/test_theme_role_duplication.py`, budget `_SHAPE_CLUSTER_BUDGET = 41` | 42 clusters against a budget measured 2026-08-25, i.e. BEFORE #463 added `SIDEBAR_GROUP_HEADING` and `SIDEBAR_GROUP_HEADING_COUNT`. Verified failing on `main` independently of any branch — the quick gate never ran this file. Reviewed: the cluster is those two plus `SIDEBAR_ROW_NEWS`, three roles with three different colours AND three different sizes that merely share the property NAMES `background; color; font-size; font-weight`. Merging them would be wrong. The budget is shrink-only and says "never raise one to make a new twin pass" — these are not twins, but that is a judgement call the owner should make, so it is logged rather than quietly raised. |
| F8 | **A dead guide is not detected as expired** | `epg_manager.needs_refresh()` expiry floor, via `ProviderDB.epg_data_end` | `epg_data_end` is the max `stop_time` of non-filler programmes, so a guide whose last entries merely run LONG reports coverage past the point where anything new can start. Measured on the owner's DB 2026-08-26: last programme *started* 10:38, `epg_data_end` read 22:00, and with `auto` (delta = half the guide depth ≈ 29.7 h vs 25 h elapsed) no refresh was due until ~16:27 — six hours during which no watch alert could possibly fire. `EpgRepository.has_future_programmes()` now measures this correctly and Watch Alerts reports it honestly, but the REFRESH still keys off `epg_data_end`. Not fixed inline because the floor is the exact heuristic repaired twice for re-fetch loops (#285 BiggyJuke, #320 TREX): any new trigger needs its own "did the last fetch actually produce future starts" guard or it re-fetches forever against a feed that lags real time. Own slice. |

---
| F22 | **Two drift guards pass with the behaviour they guard removed** | `tests/test_progress_paint.py:76`, `tests/test_recommendations_scale.py:139,156` | Both assert a NAME appears in `inspect.getsource(...)`, and both names survive the mutation that deletes the behaviour. Verified: replacing a real `fetch_in_chunks(` call in `score_candidates` with a call to a function that **does not exist** left `test_recommendations_scale.py` at 9 passed — a dead import and a stale comment keep the substring alive. `test_progress_paint.py:76` has the identical shape (`assert "paint_progress" in src` over a whole module, satisfied by an import). Same defect as the credential guard repaired in #560, which is the template: call the real thing and assert the outcome. Not fixed inline because each needs its own executable replacement, and the paint one needs a rendered-geometry assertion rather than a text check. |
| F23 | **Metadata is stored per channel row, not per title** | `metadata` table (652,216 rows) joined 1:1 from `ChannelDB.metadata_id` | The same film's plot, cast and artwork are stored once per provider variant. Measured on the owner's DB 2026-08-29: 652,216 rows behind 229,626 distinct `content_key`s — **2.84x redundant**, roughly 230 MB. Not a code duplicate but the same failure shape, and it is re-derived from scratch every time somebody looks at the database size. Deliberately NOT scheduled: it costs disk rather than correctness, and re-keying metadata on `content_key` touches the identity layer that Similar Titles, Other Versions and dedupe all read. Logged so the number stops being re-measured. |
| F24 | **`normalize_genre` had two consumers and one of them bypassed it** | fixed in #561 — `core/preference_engine.py` `_split_genres` | Recorded because the SHAPE keeps recurring, not because it is open. The tag layer routed genre text through `filter_utils.normalize_genre`; the recommendation engine keyed taste weights on the raw string. 743 distinct genre strings were really 394 genres, and 66,206 of 231,814 mentions (28.6%) sat on a spelling the scorer could not match. The tell was that a canonical helper existed and only one of its two natural callers used it — worth greping for directly: a helper with one caller in a codebase this size is usually a helper with two and a bug. |
| F25 | **`excluded_provider_ids=None` silently disables EVERY other exclusion axis** | `core/repositories/tag.py` `_faceted_channel_id_query` (~:1305) | The prefix, category, content-type and keyword exclusions are all applied inside `_scope_to_visible_channels`, which is called **only** when `excluded_provider_ids is not None`. So a caller that passes keywords but no provider ids — or, worse, writes the natural-looking `get_hidden_provider_ids() or None` and happens to have no hidden sources — gets every global exclusion silently dropped. Found while adding the saved-recipe shelf: that exact `or None` was in the first draft and a behavioural test caught it. The parameters look independent and are not. Fix is either to apply each axis unconditionally, or to make the coupling explicit (require the caller to pass a scope object rather than five optional sets) — deliberately NOT done inline, because this query backs the recipe results, its Show-All browse and the facet counts, and changing its scoping semantics is its own slice with its own before/after measurements. |
| F26 | **RESOLVED — the filter-transparency bar was a nine-site hand enumeration** | was: `main_window_channels.py` (measurement, params publish, reads, the `elif`, `_show_channel_filter_breakdown`'s signature/booleans/render/`or`-chain) + `main_window.py` (four button blocks, the `refresh_theme` name tuple) → now `metatv/gui/channel_transparency.py` | Adding ONE axis required edits at nine sites across two files, each a place a future axis could be forgotten — and one WAS: the adult-content gate was an axis nobody had added, so a category of 28 flagged channels rendered 0 rows under "try a different search". **Not merged blindly:** each axis genuinely differs in how it is measured (Python diff / SQL re-query with one axis lifted / `has_dead()` probe / empty-page-only) and in what its click does (four reveal for one view; the adult gate opens its Setting, because those four are filters a user can trip by accident while the gate is a choice they made). So the axes are DATA — `(key, attr, icon, handler, suffix, tooltip)` — and the differing measurement stays in `_query_channels`, which owns the session. `main_window.py` 3436 → 3403, `main_window_channels.py` 2171 → 2155, both now UNDER their ratchet rather than over it. |
| F27 | **RESOLVED — three copies of confirm/purge/report/reload, about to become four** | `main_window_favorites.py` `clear_history`, `clear_history_older_than`, + the new per-group clear | All three did the same five steps: confirm, run one repository call in a session, put a count in the status bar, then refresh History **and** Favorites (a cleared row can be a favorite, whose section would otherwise keep showing the old play count — the easiest of the five to forget in a fresh copy). Collapsed into `_confirm_and_clear_history(title, question, purge, describe)`; the three handlers are now their differing strings plus a lambda. |
| F28 | **RESOLVED — `channel.py` grew again, and it is the file the ratchet exists for** | four history-write methods → `metatv/core/repositories/channel_history.py` | Adding the per-group purge would have pushed `channel.py` 42 lines past its baseline. That file went **1016 → 4129** before the ratchet existed, which is the exact history `scripts/rebaseline_code_health.py` cites as its reason to exist — so re-baselining it for a purge method would have been the thing the guard was built to stop. `clear_history`, `clear_history_older_than`, `clear_history_in_range` and `remove_from_history` already formed one cluster (they read and write `last_played`/`play_count` and nothing else), so this is cohesion, not arithmetic. Follows the mixin pattern `channel_stats`/`channel_lens`/`channel_ingestion` already set. Net: `channel.py` 3243 → 3196, **47 under** its baseline rather than 42 over. Does NOT pre-empt docs/CHANNEL_REPOSITORY_SPLIT.md — that plan's slices are untouched. |

## Priority 0 — Correctness-adjacent violations (do first)

### P0-1 — `provider_loader.py` uses `with session` (session leak)
- **Where:** `metatv/core/provider_loader.py:400` — `with self.db.get_session() as session:`
- **Rule violated:** *"Database sessions — try/finally, never `with session`."*
  `with session` manages the transaction but never calls `session.close()`, so the
  connection leaks for every series-info store.
- **Fix:** convert to the canonical pattern:
  ```python
  session = self.db.get_session()
  try:
      ...   # existing body
  finally:
      session.close()
  ```
  Preserve the existing commit/rollback logic inside the body.
- **Accept:** no `with .*get_session()` remains in the file; series load still stores
  seasons/episodes; tests pass.

### P0-2 — EPG Browse date picker uses local date against UTC-naive storage
- **Where:** `metatv/gui/epg_view.py:435` (`today = date.today()`), consumed at
  `epg_view.py:797` (`target_date = self.date_combo.currentData()`) → passed to
  `metatv/core/repositories/epg.py:137-165`, which builds
  `day_start = datetime(target_date.year, target_date.month, target_date.day, 0,0,0)`
  and compares against UTC-naive `EpgProgramDB.start_time`.
- **Rule violated:** *"EPG times — stored as UTC-naive… never compare `.date()` directly
  against `date.today()`."* The picker offers *local* calendar days, but the repo query
  treats the chosen day as a *UTC* window. For any non-UTC user the "Today" tab shows the
  wrong slice of programmes (shifted by the UTC offset).
- **Fix (choose the consistent convention and document it):** the repo `browse_*` query
  must convert the requested *local* day into the matching UTC-naive window before
  comparing:
  ```python
  # target_date is a LOCAL calendar date chosen in the picker
  local_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=local_tz)
  day_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
  day_end   = (local_start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
  ```
  Use the machine local tz (`datetime.now().astimezone().tzinfo`). Apply the same
  conversion to the time-slot ("Morning/Afternoon/Evening") slicing at
  `epg.py:181-182`.
- **Accept:** add a unit test in `tests/` that, with a frozen non-UTC local tz, a
  programme at UTC `2026-06-01T02:00` is returned for the correct local browse day.
  Existing EPG tests pass.

---

## Priority 1 — Deduplication (pure refactors)

### P1-1 — Single helper for parsing `provider.urls` JSON
The "coerce `provider.urls` (JSON string *or* list) into a list[dict]" boilerplate is
copy-pasted in **at least 6 places**:
- `metatv/core/repositories/provider.py:71-76`
- `metatv/core/provider_loader.py:98-100`
- `metatv/core/epg_manager.py:88-94`
- `metatv/gui/main_window.py:2882`
- `metatv/gui/main_window.py:3768-3771`
- `metatv/core/repositories/provider.py:74` (and the write-back variant in
  `provider_loader.py:110` that re-serializes with `json.dumps`)

- **Fix:** add one canonical helper next to the provider repository, e.g.
  `metatv/core/repositories/provider.py`:
  ```python
  def parse_provider_urls(raw: str | list | None) -> list[dict]:
      """Coerce a ProviderDB.urls value (JSON string or list) into a list of dicts."""
      if isinstance(raw, str):
          try:
              raw = json.loads(raw)
          except Exception:
              return []
      return [u for u in (raw or []) if isinstance(u, dict)]
  ```
  Replace every site above with a call to it. Keep the existing write paths using
  `json.dumps` (per the JSON-serialization rule) but read through the helper.
- **Accept:** no remaining inline `isinstance(..., str): json.loads` for `urls`;
  provider load, EPG URL build, and stream failover all still work; tests pass.

### P1-2 — Collapse duplicated favorite-toggle into one method
- **Where:** `metatv/gui/main_window.py` — `toggle_favorite` (~line 2785) and
  `toggle_favorite_by_id` (~line 2966) are near-identical (open session → repo →
  `toggle_favorite` → set `channel.is_favorite` → status-bar message). This is part of
  the "status-set duplication (5 places)" noted in the refactor-audit memory.
- **Fix:** extract a private `_apply_favorite_toggle(channel_id) -> tuple[Channel, bool] | None`
  that owns the session/try-finally/repo/status-message, and have both public methods
  call it, then do their view-specific follow-up (details-pane refresh vs lightbox guard).
- **Accept:** both entry points behave identically to today; single source of the
  session+toggle logic; tests pass.

### P1-3 — Expand/collapse arrows hardcoded instead of `Config`
- **Where:** `metatv/gui/filter_panel.py:188`, `filter_panel.py:347`,
  `global_filter_dialog.py:233`, `global_filter_dialog.py:404` — all use literal
  `"▼"` / `"▶"`.
- **Rules violated:** *"Icons — always from Config"* AND *"Collapse/expand buttons —
  always `expand_icon` / `collapse_icon`."* `Config` already defines
  `expand_icon` (collapsed) and `collapse_icon` (expanded) at `config.py:515-516`.
- **Fix:** replace the literals — expanded → `config.collapse_icon`, collapsed →
  `config.expand_icon`. Make sure each widget has access to `self.config`.
- **Accept:** no arrow literals remain in those two files; toggling still flips the
  glyph; changing `Config.expand_icon` propagates.

### P1-4 — Hoist in-function `import` statements to module scope
- **Where:** ~8 in-function `import json` (e.g. `epg_manager.py:87`,
  `provider_loader.py:95`, `main_window.py:3770`) and ~55 function-local imports in
  `main_window.py`.
- **Why:** PEP 8 / readability; repeated re-import on hot paths; obscures real module
  dependencies. (`import json as _json` aliases also disappear once P1-1 centralizes the
  parsing.)
- **Fix:** move to the top-of-file import block unless the import exists solely to break a
  real circular dependency (leave those, add a one-line `# deferred: circular import`
  comment). Drop the `_json` alias where the helper from P1-1 now does the work.
- **Accept:** `grep -rnP "^\s+import (json|re|os)\b"` returns only genuinely-deferred,
  commented cases; tests pass.

---

### P1-5 — Per-call `ThreadPoolExecutor` for metadata fetch (thread leak)
- **Where:** `metatv/gui/main_window.py:2939` — inside the metadata-fetch path a fresh
  `executor = ThreadPoolExecutor(max_workers=1)` is created **on every channel selection**,
  used for one `submit`, and never `shutdown()`. Each call leaks a worker thread until GC.
- **Fix:** reuse the existing long-lived `self.executor` (created at `main_window.py:241`).
  Replace the local executor with `self.executor.submit(fetch_metadata)`; keep the
  `add_done_callback`. (The callback runs on the pool thread, so it already correctly
  marshals to the UI via `self.metadata_loaded.emit` — leave that intact.)
- **Accept:** no per-call executor remains; selecting many channels does not grow the thread
  count; metadata still loads.

### P1-6 — One shared Global-Exclusion predicate across all surfaces  ✅ DONE
- **Resolution:** `filter_utils.is_channel_excluded` / `channel_exclusion_criterion` / `global_exclusion_set` are the one chokepoint; all four surfaces (channel list, details "Other Versions", EPG On-Now, facet/recipe/tag counts) route through them. Behaviour changes shipped: metadata + EPG On-Now hide prefix-less region-excluded rows; tag/recipe counts reveal language-tagged rows filed under excluded regions. See `docs/FILTERING_DESIGN.md` → Tier-2 "Unified predicate".
- **Where:** three surfaces interpret the same `global_filter_excluded_categories` set differently:
  - `metatv/gui/main_window_channels.py` `_apply_python_exclusions` — **prefix-wins + region-fallback**
    (an un-excluded language prefix keeps the channel; region only decides when there is no prefix). *(current, correct rule — shipped #298)*
  - `metatv/gui/main_window_metadata.py` `_is_filtered` — **prefix-only**, no region at all (would show
    ~37k prefix-less region-excluded rows the channel list hides).
  - `metatv/gui/epg_on_now_mixin.py` `_on_now_hidden_prefixes` — builds its own hidden-prefix set.
- **Fix:** extract ONE predicate `is_channel_excluded(detected_prefix, detected_region, excluded)` (channel-list
  rule) into a dependency-free helper (e.g. `core/filter_utils.py`) and route all three surfaces through it, so
  search, Discovery/Recommendations, and EPG On-Now agree exactly (single-chokepoint; user's "everything should
  interpret the same way"). Detail: `docs/FILTERING_DESIGN.md` → Tier-2 "Open inconsistency".
- **Accept:** a search-hidden channel is hidden identically in Recommendations + EPG On-Now; one predicate, no
  parallel region/prefix logic. **Awaiting user go on the canonical rule (a behavior change to metadata/EPG).**

---

## Priority 2 — Inline stylesheets → `theme.py`

- **Rule violated:** *"Styles — use `theme.py`, never inline duplicates."*
- **Hotspots (count of `setStyleSheet(` calls):** `epg_view.py` 63, `provider_editor.py`
  36, `global_filter_dialog.py` 30, `similar_lightbox.py` 24, `filter_panel.py` 23,
  `sidebar_sections.py` 19, `details_sections.py` 17.
- **Scope guard:** only strings that are **shared across ≥2 widgets/files**, or are
  obvious repeated variants, must move to `theme.py` as named constants. A genuinely
  one-off style may stay inline — but most of these are repeated muted-label / border /
  small-font snippets (e.g. `"border: none; color: #777; font-size: 10px;"` at
  `epg_view.py:425`).
- **Fix approach (incremental, one file per commit, start with `epg_view.py`):**
  1. Grep the file's `setStyleSheet` strings; cluster identical/near-identical ones.
  2. For each cluster, add a named constant to `theme.py` (e.g. `MUTED_CLEAR_BTN`,
     `SECTION_HINT_LABEL`).
  3. Replace inline strings with `from metatv.gui import theme as _theme` references.
- **Accept:** per file, no duplicated stylesheet string remains; visual output unchanged.

---

## Priority 3 — Decompose oversized files (>1000-line standard)

**Rule:** *"Keep files under 1000 lines; one class per file."* Current violators:

| File | LOC | Suggested split |
|---|---|---|
| `gui/main_window.py` | 4178 | Extract mixins/controllers by concern: `main_window_favorites.py` (favorite/queue toggles — see P1-2), `main_window_streaming.py` (stream validation + URL failover, the `reconstruct_stream_url`/`validate_stream_url` cluster around 3700-3800), `main_window_nav.py` (chip/view switching, `_hide_all_content_views`). Keep `MainWindow` as the thin host wiring them together. |
| `gui/epg_view.py` | 2167 | Split the three tabs into their own widgets: `epg_watchlist_tab.py`, `epg_onnow_tab.py`, `epg_browse_tab.py`; `EpgView` becomes the tab-host. The browse query/date logic (P0-2) lands in the browse tab. |
| `gui/sidebar_sections.py` | 1403 | One section class per file under `gui/sidebar/` (queue, recs, alerts, favorites, history), keeping `CollapsibleSection` base in a shared module. |
| `gui/provider_editor.py` | 1120 | Extract the async connection-test/validation logic (`aiohttp` probe around 99-100) into a non-UI helper `core/provider_probe.py`; leave the form in the widget. |
| `gui/filter_panel.py` | 1061 | Extract the collapsible group-row widget and the summary-text logic into `gui/filter_group_row.py`. |

- **Order:** do the **mechanical, low-risk** extractions first (`sidebar_sections.py`,
  `filter_panel.py`), then `epg_view.py`, then `main_window.py` last (highest coupling).
- **Method:** move code verbatim, fix imports, run tests after each move. **Do not
  refactor logic during a file-split commit** — splitting and rewriting in the same commit
  makes regressions un-bisectable.
- **Accept:** each touched file under 1000 lines (main_window may need 2-3 passes); app
  launches; tests pass.

---

## Priority 4 — Lower-value cleanups (opportunistic)

- **P4-1 — Remaining status-set duplication.** The refactor-audit memory flags ~5 sites
  that build the engaged/favorite/queue sets. After P1-2, audit
  `preference_engine.py:284`, `discovery_engine.py:132-133`, `content_dedup.py:195`,
  `details_versions.py:282-283`, `details_similar.py:163-174` and centralize the
  "compute engaged-id sets" step into one helper if they truly overlap (verify first —
  some are legitimately different axes).
- **P4-2 — Stray artifact.** A 25 MB PostScript file literally named `--help` sits
  untracked in the repo root (ImageMagick misfire). Delete it: `rm -- ./--help`. Confirm
  it is not referenced anywhere before removing.

---

## Test & verification protocol (every task)

1. `venv/bin/python -m pytest tests/ -x -q` — all green.
2. For P0 tasks, add a regression test that fails before the fix and passes after.
3. Smoke-launch once after P3 file moves: `./run.sh` (or `venv/bin/python -m metatv`)
   and confirm the app starts and the affected view renders.
4. Follow the **Session Wrap SOP** in `CLAUDE.md` when finishing a batch (tests →
   commit → docs → memory → push).

---

## Tests to write (validate behavior going forward)

**Current state:** 65 tests in `tests/` across 3 files — all filter/prefix logic
(`test_channel_filters.py`, `test_extract_prefix.py`, `test_prefix_stats.py`).
`conftest.py` provides `db_session`, `repo`, and `make_channel(...)` fixtures.
`pytest-qt 4.5.0` **is installed**, so widget-level tests are viable. The core engines
and EPG layer have **zero** coverage today — that is the biggest risk for a refactor pass.

### Golden rule for refactor safety
For every **pure refactor** task (P1–P3), write a **characterization test first** that
pins the *current* behavior, confirm it passes on `main`, then refactor and confirm it
still passes. A refactor with no test guarding it is the most likely place to silently
break behavior. Order: test → see green → refactor → see green → commit both together.

### T0 — Regression tests for the P0 bug fixes (write these as part of P0)

- **T0-1 `test_provider_loader_session.py`** — guard the session-leak fix. Hard to assert a
  leak directly; instead assert the store path runs end-to-end and commits. Use a real
  in-memory DB (`db_session` fixture pattern), feed a minimal `series_data` dict, run the
  store, and assert seasons/episodes rows exist and the session is closed
  (`session.is_active is False` after, or patch `get_session` to a spy that records
  `close()` was called). Must pass after P0-1.
- **T0-2 `test_epg_browse_timezone.py`** — the important one. With a monkeypatched non-UTC
  local tz (e.g. UTC-7), insert an `EpgProgramDB` with UTC-naive `start_time` of
  `2026-06-01T02:00:00` (which is `2026-05-31 19:00` local). Assert `browse_*` for local
  date **2026-05-31** returns it and for **2026-06-01** does not. This test should FAIL on
  current `main` and PASS after P0-2. Also cover the time-slot ("Evening") boundary.

### P0-3 — `MainWindow.closeEvent` leaks threads (cleanup-rule violation)
- **Where:** `metatv/gui/main_window.py:4168-4178`. `closeEvent` calls
  `player_manager.cleanup()`, `stream_retry_manager.stop()`, `db.close()` — but **never**
  calls these background managers that own threads/timers:
  - `epg_manager.shutdown()` (`epg_manager.py:453` — stops the QTimer **and**
    `self._executor.shutdown()` for a 2-worker pool)
  - `image_cache.shutdown()` (`image_cache.py:290` — 4-worker pool)
  - `self.executor.shutdown()` (the MainWindow-owned 4-worker pool created at
    `main_window.py:241`)
- **Rule violated:** *"Resource cleanup in closeEvent — any background manager with a
  stop()/shutdown() method must be called explicitly… GC/parent destruction is not
  sufficient for threads."* On exit, these pools/timer keep running.
- **Fix:** add the three calls to `closeEvent` before `event.accept()`. Guard each with
  `hasattr`/`is not None` like the existing `stream_retry_manager` block.
- **Accept:** app exits cleanly; no lingering `epg`/`image`/executor threads; a test that
  spies `shutdown()`/`stop()` were each called on close.

### P0-4 — Views with `on_activate()` but no `on_deactivate()` (lifecycle-rule violation)
- **Where:** `discover_view.py`, `events_view.py`, `sports_view.py`, `preferences_view.py`
  each define `on_activate()` (start QThreads / submit executor work) but **no**
  `on_deactivate()`. (`epg_view`, `content_view`, `ppv_view` are symmetric — use them as
  the template.)
- **Rule violated:** *"View lifecycle — on_activate / on_deactivate must be symmetric."*
  Concrete failure: switch away from Discover mid-load and the running `QThread`
  (`discover_view.py:325`) is never `quit()`/`wait()`-ed; on app close this can raise
  *"QThread: Destroyed while thread is still running."* Executor-backed views
  (events/sports/preferences) keep fetching after the user has left the view.
- **Fix:** add `on_deactivate()` to each: quit+wait the QThread (or set a cancel flag the
  worker checks), stop any view timers, and have `main_window._hide_all_content_views()`
  call `on_deactivate()` on the departing view (per the CLAUDE.md "safest pattern").
- **Accept:** rapid view-switching during a Discover load produces no Qt thread warnings;
  leaving events/sports cancels in-flight fetches; tests assert the host calls
  `on_deactivate` on the outgoing view.

### T1 — Characterization tests before the P1 dedup refactors

- **T1-1 `test_provider_urls_parse.py`** — pin `parse_provider_urls()` semantics so all 6
  call sites can be swapped safely: JSON string input, already-a-list input, `None`,
  malformed JSON (→ `[]`), and list containing non-dict junk (filtered out). Write it
  against the new helper; assert each old call site now returns identical results to the
  pre-refactor inline code for the same inputs.
- **T1-2 `test_favorite_toggle.py`** — pin that both `toggle_favorite` and
  `toggle_favorite_by_id` flip `is_favorite`, persist it, and post the right status
  message. Run both paths against the `repo` fixture; assert DB state and returned/observed
  status text are identical. Guards the P1-2 extraction.
- **T1-3 (cheap, no DB) `test_expand_icons.py`** — assert `filter_panel` / `global_filter_dialog`
  collapse widgets render `Config.expand_icon` when collapsed and `Config.collapse_icon`
  when expanded (pytest-qt). Guards P1-3 and prevents regression to hardcoded glyphs.

### T2 — Core-engine coverage gaps (net-new value, independent of refactor)

These modules drive correctness and recommendations but have no tests. Prioritize by blast
radius:

- **`test_content_dedup.py`** — `normalize_title()` (leading-space strip, year-range
  `(2000-2005)`, bracket/paren qualifier stripping — the exact cases fixed in session 7,
  lock them in) and the `(norm_title, media_type, year, director)` fingerprint grouping,
  including the documented compromises: director excluded for series, null-year absorption.
- **`test_preference_engine.py`** — `score_candidates()` with the explicit/implicit
  `(explicit, implicit)` tuple ordering (explicit config must dominate); minimum-support
  threshold; recency decay; the language-preference fix (English version outranks
  Italian/Polish when both present).
- **`test_discovery_engine.py`** — shelf SQL builders (genre/decade/actor/director) return
  expected channels; `is_favorite` / `in_queue` flags set correctly from the id sets.
- **`test_epg_utils.py`** — `now_utc`, `fmt_time`, `remaining_str`, `minutes_away`,
  `progress_pct`, `fmt_duration` — pure functions, trivial to cover, high regression value.
- **`test_epg_repo.py`** — `current`, watchlist, browse, time-slot queries against seeded
  UTC-naive rows (overlaps T0-2; share fixtures).
- **`test_channel_name_utils.py`** — `normalize_region_code`, `REGION_FULL_NAMES`, quality
  token parsing — the canonical lookup tables the rules forbid duplicating.
- **`test_special_content.py`** — PPV/Events/Sports detection + classification keywords.

### T3 — Widget/integration tests (pytest-qt, fill the session-7 gaps)

- **`test_filter_panel.py`** — `get_filter_state()` after programmatic toggles; expand/collapse
  state persistence; **row-click toggles the checkbox** (session-7 feature, untested);
  **right-click context menu** ("Check only 'X'", "Exclude 'X' globally…") writes
  `global_filter_excluded_prefixes`.
- **`test_genre_normalization.py`** — multilingual genre map (Drama/Drame/Dramma → Drama,
  Komödie/Comédie → Comedy); non-Latin scripts dropped (RTL width guard).
- **View lifecycle** — for any view with `on_activate`/`on_deactivate`, assert they're
  symmetric (timers started are stopped) per the CLAUDE.md rule; a small parametrized test
  over the view classes catches future asymmetric additions.

### Test infrastructure to add alongside

- A `seed_epg(session, ...)` fixture in `conftest.py` for the EPG tests (UTC-naive rows).
- A `frozen_local_tz` fixture/monkeypatch helper so timezone tests are deterministic on any
  machine — reused by T0-2, T2 EPG tests.
- Keep all new tests offline/deterministic: no real network, no real provider, no mpv.
  Mock `aiohttp` and the Xtream client; use the in-memory SQLite from `conftest.py`.

### Definition of done for the test work
- `venv/bin/python -m pytest tests/ -q` stays green.
- T0-2 demonstrably fails before P0-2 and passes after (attach the before/after in the
  commit message).
- Update the **[filter test suite memory]** count and the FILTERING_DESIGN / ROADMAP
  test-coverage sections when the suite grows (per Session Wrap SOP step 1).

---

## Appendix — Are the CLAUDE.md "Critical Rules" themselves best practices?

> **Status (2026-06-01):** the *wording* changes from this review are already applied to
> CLAUDE.md — DB-sessions and SQLite-JSON rules reworded (no longer ban the better
> solution); Styles rule softened to target duplication; Collapse/expand rule merged into
> Icons; Icons + EPG-times rules carry `<!-- target -->` notes pointing here; two new rules
> added ("Background pools/threads — owned, long-lived, and shut down" and "No unbounded DB
> work on the UI thread"). What remains below is the *code/structural* work those targets
> describe — still TODO.

Reviewed each documented rule on its own merits. Verdicts: **Sound** (keep as-is),
**Band-aid** (the rule reliably prevents a bug, but it does so by mandating discipline at
every call site instead of removing the root cause — a deeper structural fix would make the
rule unnecessary), **Reconsider** (the rule may push code toward a mild anti-pattern).

Most rules are genuinely good. The five "Band-aid"/"Reconsider" items below share one
theme — *they enforce repeated manual discipline where a single shared mechanism would be
safer.* These are the highest-leverage structural improvements in this whole plan, because
each one **eliminates an entire recurring bug class** rather than fixing one instance. Treat
them as optional-but-recommended P1.5 work, each behind its own design discussion.

| CLAUDE.md rule | Verdict | Note |
|---|---|---|
| EPG time utils from `epg_utils.py` | **Sound** | Textbook DRY / single source. |
| Collapse/expand icon convention | **Sound** | Consistency convention; cheap to honor. |
| Styles in `theme.py`, *never* inline | **Sound** (soften wording) | DRY is right; "never inline" is too absolute — a genuinely one-off style is fine inline. Reword to "no **duplicated** stylesheet string." |
| Lookup tables single-source | **Sound** | Correct. |
| **Icons always on `Config`** | **Reconsider** | Overloads a *settings/persistence* model (Pydantic `Config`) with dozens of presentation constants — two concerns in one object, and every new glyph bloats the user config schema. Better: a dedicated `metatv/gui/icons.py` (or `theme.ICONS`) constants module; reserve `Config` for things the user actually configures. Keeps the "no hardcoded literals" benefit without conflating config with theming. |
| Logging = loguru only | **Sound** | Fine project-wide consistency choice. |
| **DB sessions: try/finally, never `with`** | **Band-aid** | The rule prevents a real leak, but enshrines try/finally boilerplate at ~every query site (and spawns the sibling rule "early returns must clean up"). Root-cause fix: one `@contextmanager session_scope()` helper that does `try → yield → commit → except: rollback → finally: close`. Call sites become `with session_scope() as s:` — shorter, leak-proof, and the "early-return cleanup" rule becomes moot for sessions. This is the single biggest readability win available. |
| **SQLite JSON: manual `json.dumps/loads` every assignment** | **Band-aid** | The rule itself documents a recurring bug (forgetting the write-back `dumps`). That bug class only exists *because* serialization is manual. Root-cause fix: a SQLAlchemy `TypeDecorator` (`JSONEncoded`) that does dumps/loads in `process_bind_param`/`process_result_value` once; columns become `Column(JSONEncoded)` and you assign/read plain Python objects. Eliminates the entire "stored a Python list instead of JSON string" footgun (incl. the P1-1 provider-urls churn). |
| Qt threading via signals | **Sound** | Correct and non-negotiable. |
| QPixmap on main thread | **Sound** | Correct Qt constraint. |
| Signal-block during restore | **Sound** | Standard Qt idiom. |
| EPG notifications not from workers | **Sound** | Correct; already implemented via private signals. |
| **EPG times stored UTC-naive** | **Reconsider (root cause)** | This single decision spawns *three* defensive rules (display-convert, "never `.date()==today()`", arithmetic-in-UTC) and is the direct cause of bug **P0-2**. Storing tz-aware UTC datetimes (or documenting a single conversion boundary at the parser/repo edge) would remove the footgun class. At minimum, centralize *all* conversions in `epg_utils.py` so no view ever touches a raw `start_time`. Heavier lift (touches the schema/parser) — scope as its own task, not a drive-by. |
| EPG one-worker fetch (SQLite lock) | **Sound** (note) | Correct given current setup. Worth a footnote: enabling SQLite **WAL mode** would relax write-concurrency pain app-wide and is independently worth doing. |
| Early returns clean up acquired state | **Sound** | Good defensive rule — but see the `session_scope()` note: context managers make most instances of it automatic. |
| View `on_activate`/`on_deactivate` symmetric | **Sound** | Good rule; currently **violated** in 4 views (task P0-4). |
| Resource cleanup in `closeEvent` | **Sound** (fragile) | Right intent, but manual per-manager registration is fragile and is **already violated** (task P0-3). Sturdier: a small `self._cleanables: list` that managers register into, iterated in `closeEvent` — new managers can't be forgotten. |
| UI state persistence everywhere | **Sound** | Good product rule. |

**Recommended structural tasks distilled from the above (each its own design + commit):**
1. `session_scope()` contextmanager → migrate query sites off raw try/finally. (Supersedes the "never `with session`" rule with a *better* `with`.)
2. `JSONEncoded` `TypeDecorator` → retire manual `json.dumps/loads` discipline.
3. `metatv/gui/icons.py` constants module → move glyphs off the `Config` settings model.
4. EPG tz-aware storage (or single conversion boundary) → dissolve the cluster of EPG-time rules; fixes P0-2 at the root.
5. `closeEvent` cleanup registry → make P0-3-style omissions structurally impossible.
6. (Independent) Enable SQLite **WAL mode** to ease the one-writer constraint.

Do **not** silently rewrite these — each changes a documented convention. Propose the change,
update CLAUDE.md's rule text in the *same* commit, and keep the old rule's intent intact.

## Variant collapsing — the open performance decision (2026-08-29)

`ChannelRepository._get_all_collapsed` (`channel.py:583`) costs **5.94 s** per
list load on the owner's library against **0.04 s** with collapsing off — 150×,
and **LIMIT-independent**, because the window function runs over the whole
corpus before `LIMIT` can apply. Every search, filter change, exclusion toggle
and provider click pays it. This is the "brutally slow" report.

Two routes were investigated and **neither is ready to apply**; recording both
so the next attempt does not re-derive them.

**An expression index does not fix it.** `CREATE INDEX ... ON channels
(COALESCE(content_key,'id:'||id), id)` removes one of the three temp B-trees
but saves only ~12% (0.42 s → 0.37 s on a 300k-row synthetic corpus). A
covering form adds nothing. The cost is materialising the window over the full
set, not the partition sort. **Do not spend a slice on this.**

**`GROUP BY` + `MIN()` of a packed sort key is 3.1× faster** (0.40 s → 0.13 s
on the same corpus, two temp B-trees instead of three) — but the form measured
is **not semantically equivalent**, and the gap is the whole problem:

* Election needs `MIN(rank || id)`, where `rank` must be **fixed width** so the
  prefix dominates the lexicographic comparison. With the #454 exclusion
  penalty prepended that is two rank digits, so the `substr()` offset changes
  with the rank encoding — an off-by-one silently elects the wrong row.
* Ordering is the real obstacle. The current query orders by the
  **representative's** `name`; the fast form has only aggregates, and
  `MIN(name)` is the alphabetically smallest name in the group, which is a
  different row. Recovering the representative's name means a join back over
  every group before `ORDER BY name LIMIT n`, and that sort is a large part of
  what is being paid now.

**The third route** — electing the representative at ingestion and storing
`is_variant_rep` (the project's own "compute once at write time" principle) —
is blocked on the same #454 constraint from the other side: the penalty depends
on the user's *current* exclusion sets, which are runtime config, so a stored
representative needs a read-time correction for groups whose stored rep is
excluded. #454 is the bug where getting that wrong made **18,486 titles
disappear**, each with at least one variant the user had not excluded.

Owner's call. The three routes differ in risk, not just in speed.
