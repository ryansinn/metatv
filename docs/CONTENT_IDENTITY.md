# Content Identity & Cross-Source Dedup

**Status:** Implemented (dedup Slices 1–3, PRs #204/#205/#206/#210). This doc is the spec for the
stored `content_key` identity layer and the surfaces that collapse on it.

**See also:** `docs/DESIGN_RATIONALE.md` **DR-0009** (the *why*); CLAUDE.md Critical Rule
*"Content identity — one stored `content_key`, computed at ingestion, collapsed at read"*;
`content_dedup.py` (the older runtime fingerprint that Recommendations/Similar still use — Phase 2
will re-base those onto `content_key`).

---

## The problem this solves

Content had **no stable identity**. Five surfaces each re-derived "are these the same thing?" at read
time and disagreed:

- **Recommendations / Similar** — the rich runtime fingerprint `(norm_title, media_type, year,
  director)` (`content_dedup.build_dedup_key`).
- **Discover shelves** — a *weaker, parallel* `(normalize_title, year)` keyed dedup run post-query and
  capped to the shelf window, so dupes beyond the window leaked through.
- **Details "Other Versions"** — `normalize_title` match on demand, per selected channel.
- **Browse / Recipe Show-All / Search / tag YIELDS counts** — **no identity at all** → the same title
  appeared ×N and inflated facet counts.

Moving Categories→tags didn't break this; it *exposed* it, by surfacing the whole cross-source corpus
at once. More sources and mixed source types (Spotify/YouTube/Plex) only worsen it. So identity is
solved **once, as a data layer**, not per surface.

## Two principles (the codebase's own)

1. **Identity is computed once at ingestion → stored.** A `content_key` TEXT column on `ChannelDB`
   (indexed), computed in the same `update_detected_prefixes()` pass that writes `detected_title` /
   `detected_year`. Read everywhere; never re-derived at query/render time. (Same discipline as the
   `detected_*` fields and `tag_fingerprint`.)
2. **Identity is applied through the stored key, never a parallel read-time key.** Every collapse /
   count / variant surface keys on the stored `content_key` (NULL-guarded — see below). No surface
   re-implements a private dedup heuristic.

---

## The key (`metatv/core/content_identity.py`)

`content_key_for(channel) -> str` is an **engine-layer pure function** (DR-0007): same inputs → same
output, no DB, no config. It dispatches on a per-domain strategy (below); the only strategy implemented
today is Xtream/IPTV.

### Normalisation

`_normalize_for_key(detected_title)` — lowercase → strip non-word characters → collapse whitespace.
It operates on the **already-stripped** `detected_title` (prefix/quality/region/year/sub-dub qualifiers
removed at ingestion), so it does *not* re-parse the raw name. Two titles differing only in punctuation
or spacing collapse to the same component.

### Coarse-key fields (deliberately coarse)

| media_type      | key format                              | year |
|-----------------|-----------------------------------------|------|
| `series`, `live`| `{norm_title}\|{media_type}`            | **omitted** |
| everything else (`movie`) | `{norm_title}\|{media_type}\|{start_year}` | **kept** (first 4-digit group of `detected_year`) |

- **Year is dropped for series/live** because providers label the same series inconsistently — some
  embed a start year, some a range (`2015-2018`), some nothing. Including year would *split* the same
  production. Mirrors how `content_dedup.build_dedup_key()` already drops *director* for series.
- **Year is kept for movies** because it is a meaningful remake discriminator (same title, different
  year = different production), and movie years are typically a single clean 4-digit value. The start
  year is extracted (`"2015-2018"` → `"2015"`, `"(2024)"` → `"2024"`; junk/empty → omitted).
- **`media_type` is always included**, so "Sherlock" the live channel, the movie, and the series stay
  distinct.

### Why director and metadata-year are excluded

Both come from TMDb/OMDb, which is **not available at channel-upsert time** — the key must be computable
from stored channel-row fields alone. TV series also have many episode directors (unreliable). A coarse
key safely groups the *visible* problem (language / quality / source variants of one production) without
over-splitting. Refinement waits for canonical IDs (below).

### NULL / empty fallback

When `detected_title` is empty, the channel's own `id` becomes the norm component
(`{id}|{media_type}…`), so the row gets a **unique** key and never collapses with unrelated content.
At every *collapse* site the group key is `COALESCE(content_key, 'id:' || id)` — a bare
`PARTITION BY content_key` would merge **all** un-backfilled NULL rows into one phantom group. This
COALESCE guard is mandatory wherever the key is grouped.

### Per-domain strategy seam (Q2)

`content_key_for()` dispatches on `channel.source_domain` via `_STRATEGY_REGISTRY`; absent a domain it
uses the default `_XtreamContentKeyStrategy`. A new source type (Spotify / YouTube / Plex) implements
`_ContentKeyStrategy.compute_key()` and calls `register_strategy(domain, strategy)` — **nothing else
changes**. The seam exists now; only Xtream is filled in.

---

## Where the key is computed

`ChannelRepository.update_detected_prefixes()` (`repositories/channel.py`) computes `content_key` from
the **updated** `detected_*` values in the same batch loop, and writes it only when it changed.
- **Initial population / backfill:** `backfill_content_keys()` (chunked, 2000/batch) fills NULL keys;
  `ContentKeyBackfillTask` (`migrations/content_key_backfill.py`, gated on `content_key_backfill_version`)
  runs it once on launch.
- Because `update_detected_prefixes()` writes `detected_title` **and** `content_key` in one pass, the
  `DetectedTitleReparseTask` (which re-cleans titles) refreshes keys for free — no separate backfill
  after a title-strip rule change.

## Where the key is applied (the collapse sites)

There is **one stored key**; each surface that needs collapse reads it (none re-derive a heuristic):

| Surface | Mechanism | File |
|---|---|---|
| Recipe Show-All / Now-Plating cards | `sample_channels_by_tag_facets(collapse_variants=True)` → `_build_collapsed_sample_query` (SQLite `ROW_NUMBER()`/`COUNT()` window functions partitioned by the COALESCE key) | `repositories/tag.py` |
| Tag YIELDS counts | `count_channels_by_tag_facets(collapse_variants=True)` → `COUNT(DISTINCT COALESCE(content_key,'id:'||id))` | `repositories/tag.py` |
| Discover shelves + cards | `_dedup_cards(cards)` groups on `card.content_key` (fallback `id:{channel_id}`) | `discovery_engine.py` |
| Details "Other Versions / Sources" | `_bg_fetch_versions` queries `ChannelDB.content_key == ck` | `gui/main_window_metadata.py` |

Because the collapsed variant set **is** the details-pane "Other Versions" set (same identity), a card's
"×N" badge and the details "N versions" always agree.

### Representative pick & stable pagination

The SQL collapse picks a **deterministic representative** per group: highest quality first
(`detected_quality` ranked 4K/8K/UHD=0 → FHD/HDR=1 → HD=2 → else=3), `id` as tiebreaker. Pages are then
ordered by clean title (`COALESCE(NULLIF(detected_title,''), name)` NOCASE), so `OFFSET/LIMIT` pages are
disjoint and gap-free. `variant_count` (the `COUNT(*) OVER (PARTITION BY …)`) rides out as the ×N badge.

`_to_card` reads `channel.detected_title` (the stored clean title), never `display_title()` — the latter
re-parses `name` and misses leading-pipe prefixes like `|EN|` / `| MULTI|`.

---

## Deliberately *not* on `content_key` yet (Phase 2)

**Recommendations and the Similar lightbox** stay on the richer runtime fingerprint
(`content_dedup.build_dedup_key`, which includes director for movies). They work; re-basing them onto
the coarse key is a separate wave (DR-0009 Q1) so a working feature isn't destabilised. When they move,
`version_score` is rewritten for tag/quality preference and the representative pick refines on-screen.

## Known compromises (accepted)

- **Same-title reboots over-merge.** Two different "The Office" series collapse into one card (year is
  dropped for series). Accepted per DR-0006: a false *positive* is visible and one-click-correctable;
  a false *negative* is invisible. Per-group "not the same" correction (janitor-fed, #57/#50) is the fix
  vector, not spreading variants across the browse list.
- **Coarse vs. rich.** The ingestion key is coarser than the Recommendations fingerprint by design
  (no director, no metadata-year). It is meant to group source/quality/language variants, not to be the
  final canonical identity.
- **No global "show all variants" toggle.** Collapse is always-on; the details-pane "Other Versions" *is*
  the variant view (DR-0009 Q3).

## Migration path — canonical IDs

`content_key` is structured to **become** the canonical id. Once TMDb/IMDb metadata is wired
(ROADMAP), a channel's resolved external id (e.g. `tmdb:movie:603`) replaces the heuristic
`{norm_title}|{media_type}|{year}` string in the *same column*. Every collapse site already reads
`content_key`, so they inherit canonical identity with no surface changes — the heuristic key degrades
to the fallback for rows without a resolved id. That one-column swap is the whole point of storing an
opaque-but-stable key instead of dedup-ing per surface.
