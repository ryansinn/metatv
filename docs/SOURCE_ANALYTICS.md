# Source Analytics — Scoping & Design

**Status:** Scoping / design only. No code until the phasing in §7 is approved. This document
characterizes a **source-analytics surface** ("data-nerd tab") that quantifies what each
provider actually contains, how much it overlaps with the others, and what is *unique* to it —
so a user can decide whether a newly-added source is worth keeping or is mostly a re-skin of one
they already have.

**Lineage:** this is the UI manifestation of the *Dialect Profile* layer sketched in
[SOURCE_INGESTION_GENERALIZATION.md](SOURCE_INGESTION_GENERALIZATION.md) §6 Layer 2.7. That doc
asked "how do we characterize a source's shape?"; this one answers "and how do we *show* it."

**Author context:** written from a read-only audit of the live database
(`~/.local/share/metatv/metatv.db`, all three sources present: TREX Shared, ProSat, IPTV Ninja).
All numbers below are measured from real rows on 2026-06-13, not estimated.

---

## 1. The motivating finding (measured)

The user observed that the freshly-added **IPTV Ninja** catalog looked "almost 1:1" with **TREX
Shared**. It is — and the overlap is now quantified (distinct *live* normalized titles, key =
`lower(detected_title or name)`):

| Pair | Shared | A-only | B-only | Jaccard | Reading |
|---|---|---|---|---|---|
| **TREX ↔ Ninja** | 40,778 | 3,970 | 3,516 | **84.5%** | Ninja is ~93% redundant with TREX |
| TREX ↔ ProSat | 4,855 | 39,893 | 11,049 | 8.7% | disjoint catalogs |
| ProSat ↔ Ninja | 4,839 | 11,065 | 39,455 | 8.7% | disjoint |

Live channel counts: TREX 55,288 · ProSat 20,356 · Ninja 54,456.

**The verdict a user wants from this:** "Adding Ninja buys ~3,500 live channels you didn't
already have from TREX; the other 40,778 are duplicates. ProSat, by contrast, is 91% unique."
That single sentence is the product of this feature.

---

## 2. What we can compute **today** vs. the data gaps

### 2a. Available now (no new ingestion) — powers the entire read-only phase

Persisted per channel (`ChannelDB`, confirmed): `provider_id`, `media_type`, `name`,
`detected_title`, `detected_prefix`, `detected_quality`, `detected_region`, `detected_year`,
`is_adult`, `special_view`, `source_num`. From these, per source:

- **Counts & media mix** — live/movie/series totals.
- **Quality weights** — `detected_quality` histogram (HD/FHD/4K/RAW/…).
- **Region/language weights** — `detected_region` + `detected_prefix` histograms.
- **Prefix fingerprint** — the `detected_prefix` distribution (the source's "dialect signature").
- **Recognized vs unrecognized prefix ratio** — `detected_prefix` ∩ canonical lexicon. This is
  the *lexicon-coverage* metric and doubles as the worklist for the prefix-evaluation task.
- **Cross-source overlap & unique content** — set ops on normalized titles (§3).

### 2b. Data gaps — block the *category* pillar until closed

The user explicitly wants "category weights / most-populous categories / categories unique to a
source." That pillar is **partially blind today**:

| Field | State | Consequence |
|---|---|---|
| `category` (Xtream category *name*) | **empty for all 3 sources** | unusable |
| `category_id` (opaque numeric) | populated all media (TREX 1,417 · ProSat 746 · Ninja 1,416 distinct) | groups, but no human label |
| `source_category` (`##`-header label, **live only**) | TREX 902 · Ninja 901 · **ProSat 0** distinct | real names, but live-only and ProSat has none |

So today: category analytics works **for live TREX & Ninja** (via `source_category`), is **blind
for VOD/series and for all of ProSat**. The Xtream `get_*_categories` name maps are fetched at
load time and discarded. **Closing this is a small ingestion enabler** (persist the
`category_id → name` map per provider, or denormalize the name onto each channel). It is a
*separate PR* from the read-only view and the view must degrade gracefully without it.

---

## 3. Overlap methodology (and its known compromise)

- **Identity key, phase 1 (heuristic):** `lower(detected_title or name)`, compared *within a
  media_type* and *within a provider's distinct set*. Cheap, already indexed-ish, good enough to
  produce the headline numbers above.
- **Identity key, phase 1.5 (upgrade):** route titles through the existing
  `content_dedup` normalizer (strips quality tokens, punctuation, articles) for a truer match —
  the same normalization recommendations already use. This is the correct long-term key and
  removes false "unique" rows caused by trivial punctuation/quality differences.
- **Metrics:** per ordered pair — `shared`, `A-only`, `B-only`, Jaccard `|A∩B| / |A∪B|`. For N
  sources, an **N×N overlap matrix** (the "which sources overlap most with each other" view).
- **Unique content drill-down:** "what is ONLY on source X" = `X.titles − ⋃(others)`, listed as
  real channels. This is the high-value "is X pulling its weight?" panel.
- **Compromise (documented, mirrors `content_dedup` debt):** title-string identity will both
  over-merge (two genuinely different productions sharing a normalized title) and under-merge
  (same production with divergent names). The honest fix is canonical `tmdb_id`/`imdb_id` (see
  ROADMAP); until then the overlap % is a **heuristic estimate**, labeled as such in the UI.

---

## 4. Read-only view — panels (Phase 1)

A new content view (`SourceAnalyticsView`), stacked in `_list_layout` like `ProviderEditorView`,
entered from the **Sources** sidebar section (per-source "Analyze" affordance) with symmetric
`on_activate` / `on_deactivate`. All aggregates run **off the UI thread** (§6).

1. **Source fingerprint (per source).** Counts (live/movie/series), media mix, quality-weight
   bar, region/language top-N, prefix-recognition coverage %, adult %, untagged %.
2. **Overlap matrix (all sources).** N×N Jaccard heat-grid + the headline sentence ("Ninja is
   84.5% shared with TREX"). Click a cell → the pair's shared / A-only / B-only breakdown.
3. **Unique content (per source).** "Only on ProSat: 11,049 live titles" → drill into the actual
   channel list. The "is this source worth keeping?" panel.
4. **Categories (per source) — depends on §2b enabler; degrade gracefully without it.**
   Most-populous categories, categories unique to this source, and the channels within a unique
   category. Doubles as the surface for **spotting outlier / junk category names** to clean up.
5. **Unrecognized prefixes (per source / global).** The `detected_prefix` tokens the lexicon
   doesn't know, with counts + sample names. This is simultaneously a diagnostic *and* the
   worklist that feeds the prefix-evaluation task — and, in Phase 2, the click target for
   assigning a meaning.

Everything read-only: counts, histograms, percentages, drill-down lists. No mutation.

---

## 5. Phase 2 — user-definable space (the architectural shift to name now)

Today, prefix / quality / category *meaning* lives in **code** (`channel_name_utils.py`
canonical lexicon: `REGION_FULL_NAMES`, `_ALIAS_MAP`, `PLATFORM_CODES`, `QUALITY_TOKENS`) plus
some `config`. The user's stated direction: "eventually it will break out into user-definable
space" — assigning a meaning to an unrecognized prefix, or defining/curating categories, from
the UI.

**The design rule that keeps this from violating "single source of truth":** code stays the
**defaults**; user edits become a **separate, DB-backed overlay** that the parser consults
*on top of* the canonical tables — it **augments, never forks** them.

```
canonical code lexicon (channel_name_utils.py)   ← defaults, shipped, authoritative
        +  user overlay (new DB table)            ← per-user additions/overrides
        =  effective lexicon the parser reads
```

- One canonical lexicon still exists (rule preserved); the overlay is a clearly-labeled second
  layer, not a parallel dict in another module.
- The overlay is **user data** (belongs in the DB / a user file), not `config` glyph/presentation
  state and not a code constant — this is the "break out of config" the user described.
- The analytics tab is the natural **editing surface**: click an unrecognized prefix → see sample
  names → assign region/platform/quality → writes to the overlay → re-parse affected rows.
- Re-parse cost: assigning a meaning must re-run `update_detected_prefixes()` for affected
  channels (bounded by the token's row count), behind the existing async seam.

**Phase 2 is explicitly NOT in the first build.** Naming it now fixes the data architecture
(overlay table shape, parser consult order, re-parse trigger) so Phase 1's read-only panels are
laid out to grow editing affordances later without a rewrite.

---

## 6. Placement, threading, and the rules that govern this view

- **Placement:** a content view entered from the **Sources** section, mirroring `provider_editor`
  (added to `_list_layout`, shown/hidden, `done`-style exit). Not a top-level nav chip — it is a
  power-user/diagnostic surface, not content browsing. Phase-1 audience can be dense; the same
  view promotes to a user-facing "vet this source" tool as panels prove out.
- **Threading (hard requirement).** Every panel here aggregates over the 280k+ channel table
  (counts, GROUP BYs, set intersections). Per CLAUDE.md **"No unbounded DB work on the UI
  thread"**, all queries run via the `_run_query` async seam (`main_window_async.py`) and return
  **frozen DTOs** from `core/repositories/dtos.py` — never ORM objects across the boundary, never
  a blocking aggregate on the main thread. Use `token_ref` so switching sources cancels stale
  loads.
- **A new analytics repository.** Add the aggregation queries to a repository
  (`core/repositories/analytics.py`) returning DTOs, exercised by the seam. Keep SQL out of the
  view.
- **Styles / icons:** all glyphs from `icons.py`, all palette values from `theme.py` tokens —
  any reused stylesheet string is a role-named constant. No inline hex.
- **Render-time purity:** read `detected_*` fields directly; never call `parse_channel_name()` at
  render time (CLAUDE.md). The unrecognized-prefix panel reads stored `detected_prefix`, not a
  live parse.

---

## 7. Scope boundaries & phasing

**Phase 1 (read-only, ships first, needs no new ingestion):**
- `SourceAnalyticsView` + `AnalyticsRepository` (DTOs, async seam).
- Panels 1, 2, 3, 5 (fingerprint, overlap matrix, unique content, unrecognized prefixes).
- Overlap on the `detected_title` heuristic; label percentages as estimates.

**Phase 1.5 (small, independent):**
- Category-name persistence enabler (§2b) → lights up Panel 4 across all media types & ProSat.
- Overlap key upgraded to the `content_dedup` normalizer.

**Phase 2 (deferred — design named in §5, do not build yet):**
- User-definable prefix/category overlay table + parser consult layer + re-parse trigger.
- Editing affordances on Panels 4 & 5.

**Out of scope here (tracked elsewhere):**
- The prefix *lexicon* evaluation itself (which tokens mean what) — that is the existing
  `SONNET_EXECUTION_PROMPT_INGEST_VISIBILITY.md` Task B. This view *surfaces* the worklist; it
  does not decide the canonical meanings.
- The `WWE RAW` quality false-positive — a parser/lexicon bug folded into Task B (a bare
  normal-script `RAW`/`LIVE`/`CAM` must not be treated as a quality token; require
  `[RAW]`/`(RAW)`/superscript). Surfaced *by* this analytics work, fixed *in* the lexicon work.

**Open questions:**
1. Overlap across `media_type` or per `media_type`? (Proposed: per type; movies vs. live have
   different dup dynamics.)
2. Do we count *hidden* / adult channels in source totals, or only the visible catalog?
   (Proposed: show both — "54,456 total / 51,003 visible.")
3. Phase-1.5 enabler: denormalize category name onto each channel row, or a separate
   `(provider_id, category_id) → name` table? (Lean to the table; smaller, no row churn.)
