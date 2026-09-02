# Splitting `core/repositories/channel.py` — a surgical plan

**Status: DONE, 2026-09-02** — all four slices executed (#681, #682, #683, plus
slice 1 earlier). `channel.py` is **1733 lines**, from 4044 when this was
written and 3028 at the start of that session. Kept as the record of WHY the
file is shaped this way, and because the three lessons at the bottom apply to
the next extraction anyone attempts.

**Status when written:** planned, not started. Written 2026-08-22 for a future
session.
**Subject:** `metatv/core/repositories/channel.py` — 4044 lines, one class
(`ChannelRepository`) with 72 methods and 3741 lines of body.

---

## Why this file and not the other 24

Twenty-five files sit over 1000 lines and the code-health ratchet freezes each
at its recorded size, so none of them can grow. That makes most of them *stable
debt*, not urgent — and several should NOT be split at all:

| file | lines | verdict |
|---|---|---|
| `channel_name_utils.py` | 2573 | **leave** — lookup tables. The single-source-of-truth rule actively wants them in one place. |
| `theme.py` | 2288 | **leave** — one role-constant builder; splitting breaks the two-layer story. |
| `config.py` | 1913 | **leave** — one pydantic model. |
| `qa_checklist_window.py` | 2456 | **leave** — dev-only tooling, not shipped surface. |
| `main_window.py` | 3078 | already mixin-decomposed; residue is construction/wiring. |
| **`channel.py`** | **4044** | **split** — see below. |

`channel.py` is different because it is not one concern that got long. It is
**five concerns sharing a session object**, and the mixing has a cost the line
count does not show: every one of those concerns is forced through the same
1500-line "core query surface" file, so a change to ingestion sits three
screens from the query it can break.

## The seam already proved itself

The v0.32.0 lightbox work needed a facet query. Rather than adding a method,
it extracted `channel_lens.py` (263 lines) — and `channel.py` **shrank 85
lines**, because two predicates and two helpers that already existed moved out
with it. That is the template: *extract a concern, and take its private
helpers with it.* No behaviour change, no call-site churn, because the
repository keeps a thin delegator.

## Measured composition

```
ingestion / detected_* backfill        10 methods   1006 lines
core query surface                     35 methods   1533 lines
reconnect / provider lifecycle          5 methods    518 lines
user state (fav/hide/watch/rating)     17 methods    395 lines
identity / dedup / similar              2 methods    224 lines
counting / stats                        3 methods     65 lines
```

Ten methods hold 1006 lines of ingestion. Five hold 518 of provider lifecycle.
Those two groups alone are 38% of the file and neither is a query.

---

## The plan: four slices, largest-value first

Each slice is independently shippable, and each one is **behaviour-preserving
by construction** — the extracted module is imported back and the repository
keeps a delegating method, so no caller changes. Verify with the existing suite;
a slice that needs a test change is a slice that changed behaviour, which is
the signal to stop and look.

### Slice 1 — `channel_ingestion.py` (~1000 lines out)

Move: `update_detected_prefixes`, `_process_prefix_batch` (334 lines, the
single largest method in the file), `_commit_prefix_batch_with_retry`,
`_propagate_region_from_siblings_impl`, `_propagate_tmdb_from_title_siblings_impl`,
`backfill_content_keys`, `backfill_tmdb_ids`, `select_genre_backfill_candidates`.

Why first: biggest single reduction, and the cleanest boundary in the file —
this is the *write* path (CLAUDE.md's "compute once at ingestion" rule lives
here), and it shares almost nothing with the read path beyond the session.

Watch for: `_retry_on_lock` is used by both ingestion and enrichment. Leave it
in `channel.py` and import it, or promote it to a shared `_session_retry.py` —
do NOT copy it.

### Slice 2 — `channel_provider_ops.py` (~520 lines out)

Move: `reconnect_engaged_content`, `get_reconnect_candidates`,
`prune_provider_content`, `provider_ids_with_tmdb_candidates`,
`delete_by_provider`.

Why second: a self-contained lifecycle concern (add/refresh/delete a source),
and the one carrying the most live risk — the FK-off manual-prune rule and the
stream-ID-reuse detection both live here. Isolating it makes that code
reviewable on its own, which it currently is not.

Watch for: `prune_provider_content` must keep pruning **every** child table by
hand (foreign keys are OFF; `content_tags` once leaked 1.24M rows). Moving it
must not silently drop a table — diff the table list before and after.

### Slice 3 — `channel_enrichment.py` (~350 lines out)

Move: `apply_metadata_harvest`, `apply_tmdb_enrichment`,
`select_tmdb_enrichment_candidates`, `missing_tmdb_by_source`,
`tmdb_enrichment_funnel`, `count_metadata_enrichment_candidates`.

Why third: cohesive, low-risk, and it is the group most likely to grow when
TMDb/OMDb are finally verified end to end — better to give it a home before
that rather than after.

### Slice 4 — `channel_user_state.py` (~400 lines out), optional

Move: `mark_watched`, `mark_watched_bulk`, `record_watch_progress`,
`get_favorites_dto`, `clear_unavailable_favorites`, `assign_user_category`,
`get_hidden_channels`, `count_watched_matching`.

Why last and optional: these are small and individually clear, so the gain is
tidiness rather than comprehension. Do it only if the file is still unwieldy
after 1–3. **Do not** move anything that touches the `ChannelStateBus` contract
without re-reading that rule first.

### What deliberately stays

`get_all`, `_apply_channel_filters`, `_get_all_collapsed`, `search`,
`get_similar_channels`, `get_content_key_siblings`, the DTO mappers and the
count helpers. That is the **core read surface** — the thing callers mean when
they say "the channel repository" — and it should be what is left when the
other concerns move out. Projected: **~1500 lines**, still over the 1000 line
guideline but coherent, and reachable in one sitting.

---

## Rules that constrain this work

Read these before starting; each has bitten this file before.

1. **A delegator, not a re-export.** `ChannelRepository` keeps a thin method
   that forwards (as `get_lens_channels` does today). Callers must not have to
   learn a new import.
2. **Take the private helpers with the concern.** The `channel_lens` extraction
   shrank the file precisely because `person_predicate`/`genre_predicate` went
   with it. A move that leaves helpers behind grows the total.
3. **Annotations must resolve in their new home.** Local Python is 3.14 (lazy
   annotations, PEP 649); CI is 3.12 (eager). A function annotated with a name
   its new module never imports passes locally and fails CI at import. Check
   every annotation on every moved function.
4. **ORM must not cross the session boundary** — moved code keeps returning
   DTOs, never live ORM objects.
5. **`session_scope()` for anything new**; do not carry `get_session()` debt
   into a fresh module.
6. **Rebaseline once, at the end.** Each slice shrinks `channel.py`; the ratchet
   allows shrinking freely, so no rebaseline is needed until a NEW file lands
   over 1000 lines (none should).

## How to know it worked — and what actually happened

- `channel.py` under ~1600 lines. → **1733.** Close, and the shortfall is
  deliberate: `count_watched_matching` counts through `_apply_channel_filters`,
  so it belongs to the core query surface despite its user-state name.
- Every new module under 1000 with no baseline entry. → **held**
  (628 / 380 / 366).
- Full suite green with **no test edits**. → **held for slices 2 and 3** (991
  and 1,333 tests). Slice 4 needed **one import line** changed, for a reason
  worth recording rather than hiding: see below.
- `rebaseline_code_health.py` reports `channel.py` shrinking at each step. →
  3028 → 2443 → 2103 → 1733, and `get_session()` never moved.

## What the four slices taught, for the next extraction

1. **Take the whole concern, not the plan's list.** Every slice moved more
   members than planned, and every time the reason was the same: a private
   helper the plan left behind was shared with methods it also left behind.
   A helper separated from its users turns a private detail into a
   cross-module dependency. Slice 3 moved 11 where 6 were named; slice 4 moved
   15 where 8 were named.
2. **Sweep the new module's AST for free names before running anything.** Walk
   it for `Name` loads that resolve against neither its imports nor a local
   binding, discounting function-local imports. Slice 2 had seven such names,
   slice 3 had two — and one of slice 3's (`_start_year_int`) is in a branch
   **no test reaches**, so it would have failed at import on CI's
   eager-annotation 3.12 rather than locally. It costs a second and saves a CI
   cycle.
3. **A shared helper may have to move somewhere neither module owns.** Slice 4
   could not import `_channel_text_search_predicate` back from `channel.py` —
   that is circular. It went to `search_ranking.py`, which imports no channel
   module, and lost its underscore because a helper two modules use is not
   module-private. That is the one test edit above: CLAUDE.md requires even the
   string form to name the DEFINING module, so the test's import had to follow.

## What is left in `channel.py`

The core read surface, which is what should be left: `get_all`,
`_apply_channel_filters`, `_get_all_collapsed`, `search`,
`get_similar_channels`, `get_content_key_siblings`, the DTO mappers, the count
helpers — and `count_watched_matching`, for the reason above. It is still over
the 1000-line guideline and that is fine: the guideline is a place to stop and
look, and what is there now is one concern.

## Sequencing against the theme overhaul

These do not collide. The refactor is entirely `core/repositories/`; the theme
and layout work is entirely `gui/`. They can run in either order or in
parallel — the mockup/design pass does **not** need to wait for this.
