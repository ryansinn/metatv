# Sonnet Execution Prompt — Source Analytics (read-only, Phase 1)

Paste the block below into a fresh Claude Sonnet session (with tools, in this repo). It builds
the **read-only** source-analytics surface scoped in `docs/SOURCE_ANALYTICS.md`. Read that doc
first — it is the design this prompt implements, including the measured overlap numbers, the
data gaps, and the Phase-2 architecture you must lay out for (but NOT build).

Also read `docs/SONNET_EXECUTION_PROMPT_BAND7.md` for the anti-pattern banner — same rules apply.

---

````text
You are an implementing engineer in the MetaTV repository (Python/PyQt6 IPTV client). Build the
read-only Source Analytics view from docs/SOURCE_ANALYTICS.md. PHASE 1 ONLY — do not build the
Phase-2 user-editable overlay; only leave the code shaped so it can grow later.

════════════════════════════════════════════════════════
⛔ ANTI-PATTERNS THAT GOT PRIOR PRs DOWNGRADED — DO NOT REPEAT ⛔
════════════════════════════════════════════════════════
(Full text in docs/SONNET_EXECUTION_PROMPT_BAND7.md. The four that matter most here:)
  1. SHAPE-ONLY / ZERO-RESULT TESTS. Every behavior change ships ≥1 test that EXECUTES the
     changed path against a real file-backed tmp_path SQLite (NOT :memory:, whose pooled
     connections each get an empty DB; call create_tables()) and asserts the outcome that would
     break. "import works" / "method exists" / substring-in-source is NOT coverage.
  2. BLOCKING THE UI THREAD ON DB WORK. Every aggregate here scans the 280k+ channel table.
     CLAUDE.md "No unbounded DB work on the UI thread" is absolute: queries run via the
     _run_query async seam (main_window_async.py) and return DTOs. A GROUP BY on the main thread
     is an automatic reject.
  3. RETURNING ORM OBJECTS ACROSS THE SESSION BOUNDARY. query_fn returns frozen DTOs / plain
     dicts only. An ORM object read after session_scope() exits raises DetachedInstanceError.
  4. INVENTING A THIRD PATTERN, or hardcoding a hex/glyph. session_scope() for DB, signals for
     cross-thread, loguru, icons.py for glyphs, theme.py tokens for palette. Re-read the relevant
     CLAUDE.md Critical Rule before any shortcut.

ONE CONCERN PER PR. Branch each PR off `main`. Run `venv/bin/python -m pytest tests/ -q` green
before committing. End commit messages with the Opus co-author footer. Do NOT merge — owner merges.

Provider IDs in the live DB (for manual verification only — tests use synthetic data):
  TREX  = 4814008b-38ab-4db1-b790-0e22aaec89e1
  ProSat= 3ae8ea40-db37-4a96-9cf5-1191292d78ef
  Ninja = 41241966-31f3-4f1e-bf2a-6bf470f414be

────────────────────────────────────────────────────────
PR 1 — Analytics repository + read-only view (the headline)
────────────────────────────────────────────────────────
GOAL: a Sources → "Analyze" content view that answers "is this source worth keeping, or is it a
re-skin of one I already have?" Needs NO new ingestion — everything is computable from existing
ChannelDB fields (see SOURCE_ANALYTICS.md §2a).

BUILD:
  • metatv/core/repositories/analytics.py — an AnalyticsRepository (constructed from a session,
    like the other repos) with methods that return FROZEN DTOs (add them to
    core/repositories/dtos.py):
      - source_fingerprint(provider_id) -> SourceFingerprintDTO:
          counts {live,movie,series,total}, quality-weight histogram, region/prefix top-N,
          prefix recognition coverage (recognized vs unrecognized count, using the canonical
          channel_name_utils lexicon — IMPORT it, do not re-list tokens), adult %, untagged %.
      - overlap_matrix(provider_ids, media_type) -> OverlapMatrixDTO:
          for each ordered pair, {shared, a_only, b_only, jaccard}. Identity key (PHASE 1) =
          lower(detected_title or name), DISTINCT within (provider, media_type). Keep the key in
          ONE helper so the Phase-1.5 swap to the content_dedup normalizer is a one-line change.
      - unique_titles(provider_id, media_type, limit) -> list[ChannelRowDTO]:
          titles present on this source and on NO other provider (drill-down list).
      - unrecognized_prefixes(provider_id|None) -> list[PrefixStatDTO]:
          detected_prefix tokens NOT in the lexicon, with count + a few sample names.
    All SQL lives here; the view never opens a session.

  • metatv/gui/source_analytics_view.py — SourceAnalyticsView(QWidget), stacked in _list_layout
    in main_window like ProviderEditorView (add_widget, setVisible(False), on a `done` signal to
    exit). Panels: fingerprint, overlap matrix (N×N + headline sentence), unique-content
    drill-down, unrecognized-prefix list (SOURCE_ANALYTICS.md §4 panels 1,2,3,5 — NOT the
    category panel, that's PR 2).
      - Symmetric on_activate()/on_deactivate() (start/stop + cancel pending). _hide_all_content_
        views() must deactivate it like the other views.
      - ALL data via self._run_query(...) on MainWindow with token_ref so switching the analyzed
        source drops stale loads. The view receives DTOs on the main thread and renders.
      - Entry point: a per-source "Analyze" affordance in the Sources sidebar section (mirror how
        the edit affordance enters provider_editor). Add a tooltip (CLAUDE.md tooltips rule).
      - Glyphs from icons.py (add any missing), palette from theme.py tokens, reused styles as
        role-named constants. Label overlap % as an "estimate" (heuristic key — SOURCE_ANALYTICS
        §3 compromise).

GUARDRAILS:
  • Multi-source by design (memory: feedback_multi_source_design): the matrix must handle N
    providers, not hardcode 3. Two providers, or one, must render sanely (one source → no overlap
    matrix, just the fingerprint).
  • No parse_channel_name() at render time — read stored detected_* fields (CLAUDE.md).

TESTS (behavioral, per anti-pattern #1) — file-backed tmp_path Database, create_tables(), insert
synthetic ChannelDB rows across ≥2 provider_ids with KNOWN overlap, then:
  • AnalyticsRepository.overlap_matrix: construct e.g. provider A = {alpha,beta,gamma}, B =
    {beta,gamma,delta}; assert shared=2, a_only=1, b_only=1, jaccard=2/4. THIS is the regression
    surface — the set math, not the DTO shape.
  • source_fingerprint: rows with mixed detected_quality/detected_prefix → assert the histogram
    counts and the recognized-vs-unrecognized split (include one token in the lexicon and one
    not; assert the unrecognized one lands in the unrecognized bucket).
  • unique_titles: a title on A only vs. a title on both → assert only the A-only title returns.
  • View slot: build the view via __new__, hand it a real QListWidget/labels (module qapp
    fixture, headless), call the render slot with a hand-built DTO, assert the rendered rows
    (overlap headline text, unique-count). Pin the MAIN-THREAD half, not the worker.
  • DO NOT write a test asserting "method exists" or "import succeeds" as if it were coverage.

────────────────────────────────────────────────────────
PR 2 — Category-name persistence enabler + category panel
────────────────────────────────────────────────────────
THE GAP (SOURCE_ANALYTICS.md §2b): ChannelDB.category is empty for all sources; only opaque
category_id is stored (and source_category only for live TREX/Ninja, never ProSat). So category
analytics is blind for VOD/series and all of ProSat. The get_*_categories name maps are fetched
at load and discarded.

REQUIRED OUTCOME:
  • Persist the category_id → name mapping per provider at ingest. PREFER a small table
    (provider_id, category_id, media_type, name) over denormalizing onto every channel row (no
    280k-row churn). Populate it from the get_*_categories responses already fetched during load.
    Backfill on next refresh; missing names degrade gracefully (panel shows category_id).
  • AnalyticsRepository.category_breakdown(provider_id) -> CategoryStatsDTO: most-populous
    categories (name + count), categories UNIQUE to this source, and the channels within a unique
    category. Add SOURCE_ANALYTICS.md §4 Panel 4 to the view.
  • This panel is ALSO the surface for spotting outlier/junk category names — render them plainly
    so they're easy to eyeball.

GUARDRAILS:
  • Do not change the channel store loop's identity/merge logic. This is additive: a new mapping
    table + its population call. The fetch already has the category responses in hand — thread
    them to the store step; don't add a second network round-trip.
  • If wiring the name map through the existing fetch path is more than a localized change, STOP
    and record it as a follow-up rather than restructuring the ProviderPlugin contract.

TESTS: file-backed tmp DB — store a provider's categories + channels with category_ids, then
assert category_breakdown returns the right NAMES and counts, and that a category present on only
one provider is reported as unique. Behavioral, not shape.

OUT OF SCOPE for both PRs (Phase 2 — design is in SOURCE_ANALYTICS.md §5, DO NOT build):
  • User-definable prefix/category overlay table, parser consult-order changes, re-parse-on-edit,
    and any editing affordance. Phase 1 is READ-ONLY. Leave the view shaped to grow edit controls
    later (e.g. the unrecognized-prefix rows are obvious future click targets) but ship none.

────────────────────────────────────────────────────────
WRAP-UP (per CLAUDE.md Session Wrap SOP)
────────────────────────────────────────────────────────
Per PR: tests green → commit (Opus co-author footer) → update docs (tick the item in
SOURCE_ANALYTICS.md §7; note anything deferred) → update memory if a new pattern landed → push
the branch → report what landed and what was deferred. Do not merge.
````
