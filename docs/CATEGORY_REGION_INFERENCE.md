# Category-Supplemented Region Inference — Phase 2 Implementation Plan

**Status:** Design / implementation plan. No code until the open decisions in §10 are settled.
**Source:** `SESSION_SUMMARY_2026-06-14.md` (Issue #2 — German channel with no language indicator;
Gap #1 — language metadata not explicit). This plan is the rigorous, debt-free realization of that
report's "Phase 2."

**Guiding principle (owner directive):** *the individual channel's own data is the source of truth;
the category only **supplements** it where the channel's data is lacking.* We **err on the side of
valid data** — a channel whose region we cannot establish with confidence stays **unknown**, never
guessed. "Unknown" is a correct answer; a wrong region is not.

---

## 1. The problem (verified against the live DB)

Many channels carry an explicit region in their name (`EN - …`, `DE - …`) → parsed into
`detected_region` at ingestion. But a large population (e.g. `"Michael (2026)"`, German per the
stream audio) has **no name prefix** → `detected_region` and `detected_prefix` are NULL → the UI
shows no region. Yet these channels sit in a `category_id` whose *other* members are
overwhelmingly German. The region signal exists in the data; it's just **implicit in the category,
not explicit on the channel**.

**The opportunity:** use the channels that *do* have an explicit region to characterize each
category, then backfill the region onto the channels in that category that *don't* — but only when
the category is linguistically coherent enough to justify it.

---

## 2. The trap this plan engineers against (review of the report's overgeneralization)

The report concludes "the Xtream provider organizes channels by language via `category_id`." That is
true for the *sampled* categories on *one* provider — **not a universal law**. Real catalogs also
bucket by **genre, "VIP"/"4K"/"NEW", adult, or mixed country**. A "Sports" or "Action" category has
no dominant language. Three hard constraints follow, and they are the difference between this being a
quality feature and a debt-generating one:

1. **Confidence gating is mandatory.** We characterize a category only from its channels that have an
   *explicit* region, and we **apply** the result only when the dominant region is both
   well-supported and dominant. Mixed/genre categories fall below the bar and yield **no inference**.
2. **`category_id` is per-provider.** id `100` = German *on this provider only*. The profile is keyed
   by `(provider_id, media_type, category_id)`. (Xtream category ids can also collide across
   live/vod/series, hence `media_type` in the key.) This honors the multi-source design regulation.
3. **We infer a region, not a guaranteed audio language.** The existing field is `detected_region`
   (a region/locale code, with the documented language/region overloading in `channel_name_utils`).
   We infer the **same kind of value from a different evidence source** — we do **not** introduce a
   separate "language" axis (that would be new semantic debt; the overloading is tracked elsewhere).
   UI copy says "region · inferred from category," never "Language: German."

---

## 3. Data model

### 3a. New table — `CategoryProfileDB` (the category's observed region signal)
Keyed by `(provider_id, media_type, category_id)`. Records *what we observed* for every category
(applied or not) — useful for inference, the Source Analytics category panel, and debugging.

| Column | Notes |
|---|---|
| `id` (PK) | `f"{provider_id}:{media_type}:{category_id}"` |
| `provider_id` (idx) | per-provider scoping |
| `media_type` | live / movie / series |
| `category_id` | provider's opaque id |
| `dominant_region` | top region code among explicit-region channels, or NULL if none |
| `confidence` | `dominant_count / explicit_count` (0.0–1.0) |
| `explicit_count` | channels in this category with a non-empty `detected_region` |
| `total_count` | all channels in this category |
| `applied` | bool — whether it cleared the bar (§4) and was backfilled |
| `computed_at` | timestamp |
| `user_override_region` | **NULL; reserved** for the future user-definable overlay (SOURCE_ANALYTICS §5). Designed-for, not built. |

`dominant_region` codes come from `channel_name_utils` (canonical lookup — no parallel dict).

### 3b. New channel column — `inferred_region`
- `ChannelDB.inferred_region` (VARCHAR, indexed, nullable). The region supplied **by the category**,
  set **only** when `detected_region` is NULL/empty *and* the category is `applied`. NULL otherwise.
- `detected_region` is **unchanged** — it remains the channel's *own explicit* signal and is **never
  overwritten**. This separation is what preserves the source-of-truth hierarchy and the
  explicit-vs-inferred provenance.
- **Effective region** = `detected_region or inferred_region` — a trivial COALESCE. Exposed as a DTO
  property / a `region_source` ("explicit" | "category" | None) derived field; **not** a redundant
  stored column (would be derivable → debt).

No `detected_language` column (rejected — see §2.3 and §10 Q2).

---

## 4. The inference algorithm (ingestion-time, gated)

Runs as a new ingestion phase **after** `_update_prefixes_in_thread()` (needs `detected_region`
populated) and before stats — i.e. a new `_infer_category_regions_in_thread()` at
`provider_loader.py:~204`, scoped to the just-loaded provider.

```
for each (provider_id, media_type, category_id) in the just-loaded provider:
    rows           = channels in that category
    total_count    = len(rows)
    explicit       = [r.detected_region for r in rows if r.detected_region]
    explicit_count = len(explicit)
    if explicit_count == 0:
        dominant_region, confidence = None, 0.0
    else:
        dominant_region, dominant_count = most_common(explicit)
        confidence = dominant_count / explicit_count
    applied = (explicit_count >= MIN_SUPPORT_EXPLICIT) and (confidence >= MIN_CONFIDENCE)
    upsert CategoryProfileDB(...)            # always record the observation
    if applied:
        bulk UPDATE channels
           SET inferred_region = dominant_region
         WHERE category matches AND (detected_region IS NULL OR '')   # never touch explicit rows
```

- **`MIN_SUPPORT_EXPLICIT = 20`**, **`MIN_CONFIDENCE = 0.80`** — conservative defaults (tunable via
  config, §10 Q1). Rationale: 20 explicit samples guard representativeness (a 3 000-channel category
  with 5 prefixes is not characterized); 0.80 dominance rejects mixed categories (a 50/50 DE-FR
  category yields `confidence=0.50` → not applied).
- **Explicit rows are never written** — the `WHERE detected_region IS NULL OR ''` guard enforces the
  hierarchy at the SQL level, not just by convention.
- **Idempotent + versioned:** gate the phase on a `_CATEGORY_INFER_VERSION` constant (mirrors
  `_PREFIX_PARSE_VERSION`); bumping it on a threshold change forces a recompute on next load. A full
  provider load re-runs this anyway, so staleness from re-bucketing self-heals.
- **One aggregation + one bulk UPDATE per provider**, on the worker thread (never main).

---

## 5. How the inferred value flows through the app

| Consumer | Uses inferred_region? | Why |
|---|---|---|
| **Details pane / channel list chip** | **Yes, marked.** Effective region shown; inferred renders as a *distinct* chip (outline + tooltip "inferred from category · 87%") | User sees the supplement and can judge it |
| **Filtering (region facet)** | **Yes.** Filtering "DE" surfaces inferred-DE channels too | That's the point — surface prefix-less regional content |
| **Recommendation scoring (preference_engine attribute weights)** | **No (initially), or confidence-discounted** | A wrong inference must not silently bias scoring; hold back until validated (§10 Q3) |
| **Cross-source dedup fingerprint** | **No** | Fingerprint is `(norm_title, media_type, year, director)` — region isn't a key; leave it out |
| **Source Analytics category panel** | **Yes** — reads `CategoryProfileDB` directly | Same table; no second aggregation |

The explicit-vs-inferred distinction is **never collapsed** in the data; only the *effective region*
convenience is computed at the edge.

---

## 6. Integration points (exact)

- **Migration:** add `("channels", "inferred_region", "VARCHAR")` to the `_migrate()` list
  (`database.py:385`). The new `CategoryProfileDB` table auto-creates via `Base.metadata.create_all`
  (idempotent; existing DBs get it on next startup). Index `inferred_region` and
  `CategoryProfileDB.provider_id`.
- **Ingestion phase:** new `_infer_category_regions_in_thread()` in `provider_loader.py`, called after
  line 203, with a `self.progress.emit(...)` step (re-band the 87–97% range).
- **Repository:** a new `CategoryProfileRepository` (or methods on `ChannelRepository`) holding the
  aggregation + bulk-update SQL — **all SQL lives in the repo**, none in the loader.
- **Render:** add `inferred_region` (and the derived `region_source`) to the channel display DTOs; UI
  reads stored fields only (pure DB read — extends the "Channel name processing — ingestion-only"
  rule to category-derived fields; update that CLAUDE.md rule to name `inferred_region`).
- **Lookup data:** region codes exclusively from `channel_name_utils` (single source of truth).

---

## 7. Answers to the report's four "Questions for Opus"

1. **Compute at ingestion / cache / on-demand?** → **Ingestion-time, stored.** The
   ingestion-only-then-pure-read rule and the 240k-row scale forbid on-demand joins at render. The
   `CategoryProfileDB` table is the cache; `inferred_region` is the denormalized result.
2. **Explicit `detected_language` column vs computed property?** → **Neither, exactly.** A stored
   `inferred_region` column (not a render-time property — that'd be a join at 240k scale), and **not**
   `detected_language` (no new language axis; reuse region semantics). Effective region is the only
   computed (edge) value.
3. **Async-dependency removal beyond ratings?** → **Out of scope here** (report Gap #2/#3 = a separate
   "move immediate raw_data into `load_basic()`" concern). Noted, not folded in — one concern per PR.
4. **Provider schema registry?** → **Out of scope (Phase 4).** This plan needs no per-provider schema
   doc; it derives purely from `detected_region` + `category_id`, which every Xtream provider supplies.

---

## 8. Pros & cons

**Pros**
- Recovers region for thousands of prefix-less channels using the channels' **own** explicit data —
  not an external assumption.
- **Confidence-gated**: mixed/genre categories produce no inference → honors "valid data over
  assumptions."
- **Ingestion-time + stored + pure read** → matches CLAUDE.md rules; zero main-thread cost at 240k
  scale.
- **Provenance preserved** (explicit vs inferred + confidence) → honest UI, auditable, future
  user-override-ready.
- **Synergy**: the `CategoryProfileDB` table is exactly what Source Analytics' category panel needs —
  one table serves both features.
- **Multi-source correct** (keyed by provider/media_type).

**Cons / risks (and mitigations)**
- *Categories aren't always linguistic.* → Confidence gate + we only fill NULLs (low blast radius) +
  UI "inferred" marker. Residual: a genre category that's coincidentally single-language infers a
  (correct-by-coincidence) region — harmless since it only fills unknowns.
- *Region ≠ audio language.* → UI says "region · inferred from category," never asserts audio
  language. The "Michael" case matched reality but remains an inference.
- *Threshold tuning is provider-dependent; conservative defaults leave some inferable channels
  unknown (false negatives).* → Acceptable and intended: prefer unknown over wrong.
- *Staleness if a provider re-buckets.* → Recompute every load (already happens) + version constant.
- *Feeding scoring could amplify a wrong guess.* → Held back from recommendation weights initially.

---

## 9. Behavioral test matrix (no shape tests — execute the path, assert outcomes)

File-backed `tmp_path` SQLite, `create_tables()`, synthetic channels with known category
distributions:

1. **Confident backfill:** category A = 80 channels `detected_region="DE"` + 20 NULL → profile DE,
   confidence 1.0, explicit_count 80, `applied=True`; the 20 NULL get `inferred_region="DE"`.
2. **Mixed category refused:** category B = 50 DE / 50 FR explicit → confidence 0.50 < 0.80 →
   `applied=False`; **no** channel gets `inferred_region`; profile still records DE@0.50 for analytics.
3. **Thin support refused:** category C = 3 000 channels, 5 explicit DE → `explicit_count=5 < 20` →
   `applied=False`; no backfill.
4. **Explicit never overwritten:** a channel with `detected_region="EN"` inside a DE-dominant category
   keeps `EN`; its `inferred_region` stays NULL; effective region = `EN`.
5. **Cross-provider isolation:** provider1 cat 100 → DE, provider2 cat 100 → FR; each provider's NULL
   channels resolve to their own provider's profile.
6. **Effective region + provenance:** assert `region_source` is "explicit" / "category" / None for the
   three cases and `effective_region` = COALESCE.
7. **Idempotence / version bump:** re-running the phase yields identical results; bumping
   `_CATEGORY_INFER_VERSION` triggers recompute.

---

## 10. Scope boundaries & open decisions

**Out of scope (record, don't build):**
- **Category-name persistence** (SOURCE_ANALYTICS §2b enabler). This plan derives from `detected_region`
  and needs no category names. If/when names land, a category literally named "DE | FILME" becomes a
  *corroborating* signal that can raise confidence — layer it then, don't block on it.
- **Separating language from region** (the `detected_region` overloading debt) — explicitly untouched.
- **User override of category profiles** — table has the reserved `user_override_region` column;
  the editing UI is the deferred SOURCE_ANALYTICS §5 overlay, not this plan.
- **Feeding inferred region into recommendation scoring as a hard signal** — held back (§5).
- **Async-dependency audit** (report Gap #2/#3) — separate concern.

**Open decisions for the owner:**
1. **Thresholds** — `MIN_SUPPORT_EXPLICIT=20`, `MIN_CONFIDENCE=0.80`. Accept as conservative defaults?
   Expose in config for tuning?
2. **Confirm "region, not language"** framing (reuse `detected_region` semantics, no new axis).
3. **Recommendation scoring** — keep inferred region out of attribute weights for v1 (recommended), or
   feed it at a confidence discount?
4. **UI treatment** — inferred chip style: outlined + tooltip with category + confidence% (proposed).
