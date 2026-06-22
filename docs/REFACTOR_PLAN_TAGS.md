# Tags / Attribute Model — Implementation Plan (DR-0005)

The design is settled in **DR-0005** (docs/DESIGN_RATIONALE.md). This is the *how* —
the concrete schema, the one decomposer, the feeders, confidence, and the slice order.
Each slice below is a focused, Sonnet-implementable PR; Opus reviews.

## North star (from DR-0005)
`channel = 1 category` is the restriction. Many-to-one tags dissolve it. Every **feeder**
(provider category, `##…##` header, name-parse, genre, EPG) runs through **one shared
decomposer** that reuses the classifiers we already own → **typed tags**. Tags carry
**provenance** (generated vs user) and **confidence** (independent multi-feeder
corroboration). Reprocess is **non-destructive** (user tags sacred). Keep `detected_*` /
`source_category` columns as the **denormalized read-cache** while read surfaces migrate.

## Schema (Slice T1)
```python
class TagDB(Base):                      # canonical tag vocabulary
    __tablename__ = "tags"
    id    = Column(Integer, primary_key=True)
    type  = Column(String, index=True)  # namespace: region|language|platform|quality|
                                        #            genre|collection|content_type|decade
    value = Column(String, index=True)  # canonical value: "US", "Netflix", "Drama", …
    __table_args__ = (UniqueConstraint("type", "value", name="uq_tag_type_value"),)

class ContentTagDB(Base):               # channel ↔ tag links + provenance/confidence
    __tablename__ = "content_tags"
    id         = Column(Integer, primary_key=True)
    channel_id = Column(String, ForeignKey("channels.id"), index=True)
    tag_id     = Column(Integer, ForeignKey("tags.id"), index=True)
    source     = Column(String)         # "generated" | "user"
    feeders    = Column(JSONEncoded)    # ["provider_category","name_parse",…] → confidence
    confidence = Column(Float, default=1.0)
    __table_args__ = (UniqueConstraint("channel_id", "tag_id", name="uq_content_tag"),)
```
Single-type tags (one type → many tags). **Cross-type relationships** (compound locales like
`UK-NOWTV` → region+platform) are links *between* single-type tags — a later slice
(`tag_relations`), not multi-typing. `TagRepository`: `get_or_create_tag(type,value)`,
`set_content_tags(channel_id, [(type,value,feeder)], source)`, `tags_for(channel_id)`,
`channels_for_tag(type,value)`, `reprocess_delete_generated()`.

## The decomposer (Slice T2) — one chokepoint, pure, no DB
`decompose(feeder: str, raw: str) -> list[tuple[str, str]]` runs `raw` through the
**existing** classifiers and emits `(type, value)` pairs:
- region ← `channel_name_utils.REGION_FULL_NAMES` / `normalize_region_code`
- language / platform ← config `*_groups` via `filter_utils.categorize_prefix`
- quality ← quality-token parse
- genre ← `filter_utils.normalize_genre` (incl. the #101 de-pollution)
- content_type ← `special_content`
- collection ← the `##…##` header label / provider-category name (canonicalized)

It does **not** invent classification — it centralizes + reuses it. Unit-tested over real
category/header/genre strings (e.g. `USA | NETFLIX | HD` → region:US + platform:Netflix +
quality:HD).

> **Updated by DR-0006 (capture-more + confidence).** `decompose()` returns `(type, value,
> base_confidence)`: the **denoted** facet at high confidence **plus** any *real* adjacent guess at
> **low** confidence — capture both, never withhold (`FR` → `language:French` high + `region:France`
> low; `US` → `region:US` high + `language:English` low; `EN` → `language:English` only, no place
> "EN"). A confident signal overrides a prior; `LAT` is a distinct language; `AR`→Arabic,
> `ARG`/`ARGENTINA`→Argentina. Confidence is *ranking/prune-priority*, never a suppression gate.
> Curated code→facet+confidence data → `channel_name_utils.py`. This **supersedes #112** (which emits
> both facets but without confidence). New slices it spawns: **provenance + confidence UI** (ships
> with capture) and **facet hierarchy / containment rollup** (`LAT` ⊂ `Spanish`).

## Feeders → decomposer (Slice T3, backfill via Migration Center)
Per channel, feed the decomposer each raw source and union the results, recording which
feeder produced each tag:
- provider category — `ChannelDB.category` (populated #102)
- `##…##` header — `source_category` + `source_quality_flags`
- name-parse — `detected_prefix/quality/region/...` (already typed → promote directly)
- genre — `raw_data.genre`
- (EPG programme genre — later)

Backfill is a **MigrationTask** (visible progress, cancellable). It is the
**non-destructive reprocess**: `reprocess_delete_generated()` → re-run the decomposer →
`set_content_tags(..., source="generated")`. User tags untouched.

## Confidence (Slice T4)
`confidence = f(count of distinct independent feeders that asserted (type,value))`. Coarse
v1: normalized feeder count. **Cross-provider agreement is the gold** (weight highest — needs
content-dedup to know X-on-A == X-on-B). Store the `feeders` list; recompute confidence from
it. Conflict semantics depend on type cardinality (region single-valued → conflict real;
genre multi-valued → not).

## Read-surface migration (Slices T5+, one PR each, behind the cache)
1. **Filter / Exclusions** → tag predicates (exclusions become `NOT tag ∈ …`).
2. **Discover shelves** → group-by tag namespace; a shelf = a tag predicate.
3. **Recommendations** → tag- + confidence-weighted.
4. **Details pane** → show tags (+ confidence), make them clickable context filters.
Keep `detected_*` as the cache until each surface is cut over; distill the invariants into
CLAUDE.md once the schema is locked.

## Parallelism / order
- **T1 (schema)** and **T2 (decomposer)** are independent → can run in parallel.
- **T3 (backfill)** depends on T1 + T2.
- **T4 (confidence)** depends on T3.
- **T5+ (reads)** depend on T3; one surface per PR, each independently reviewable.
