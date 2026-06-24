# Recipe Builder — Design Spec

> **Why this doc exists.** The recipe builder is the centrepiece of the tag-payoff pivot, and it will be
> visually overhauled. This spec deliberately separates the **functional contract (durable)** from the
> **current presentation (disposable)** so the overhaul is a *re-skin, not a re-derivation* — the styling
> can be thrown away and rebuilt, but the capabilities below must survive.
>
> Rationale & rejected options: **DR-0008** (within-facet AND/OR), **DR-0005** (a view/recipe is a query
> over the tag corpus), **DR-0007** (the engine is preference-free). Engine: `TagRepository`
> (`_faceted_channel_id_query`, `count_channels_by_tag_facets`, `sample_channels_by_tag_facets`).

---

## 1. What a recipe *is* (functional contract — durable)

A recipe is a **boolean query over facet-space**: the user assembles tag "ingredients" (facet values), the
engine returns matching channels, and the matches fill the results shelf live. A learned preference profile
is the same object with the ingredients filled by the engine instead of the user (the parked
Recommendations↔Recipes unification — revisit at recipe slice 4).

**Boolean model:**

| Relationship | Semantics | Source |
|---|---|---|
| **Within a facet — optional pool** | `OR` over the pooled values (any-of) | default |
| **Within a facet — required terms** | each `AND`'d onto the whole | a value marked `and` |
| **Across facets** | `AND` (every constrained facet must hold) | always |
| **Excludes** | `NOT` (drop any channel carrying the tag) | a value cycled to exclude |

Within one facet the result is therefore: **`(OR over pool values) AND required₁ AND required₂ …`**

**Worked examples (the justification — see DR-0008):**
- **Animation:** `(Animated OR Anime OR Manga) AND Sci-Fi` — any flavour of animation, *and also* Sci-Fi.
  (Pool = {Animated, Anime, Manga}; required = Sci-Fi.) A whole-group AND would force all four → ≈empty.
- **Kids:** `Kids AND Animated` — Kids is an *audience* constraint you intersect with a content genre; OR
  ("Kids OR Sci-Fi") is useless.

**Unambiguous by construction:** all `or` values pool together, all `and` values are required terms, so
`Sci-Fi or Comedy and Drama` = `(Sci-Fi OR Comedy) AND Drama` — no operator-precedence, no nesting to reason
about.

## 2. Scoping (durable, owned by the control layer — DR-0007)

Every results query is scoped to **visible channels on active sources** (`get_hidden_provider_ids()`) AND the
user's **Global Exclusions** (paused-aware, via `filter_utils`). The engine itself is agnostic; the recipe
view supplies these as inputs so `YIELDS` always agrees with the cloud and the channel list, and never leaks
disabled-source or globally-excluded content.

## 3. Surfaces (functional roles — durable)

- **Pantry** — the facets you can draw from; selecting one loads its values.
- **Tag cloud** — the facet's values, sized by catalogue weight; clicking cycles a value's state.
- **Recipe rail** — the assembled recipe in plain English ("Tonight's Recipe"), the live `YIELDS` count, and
  per-ingredient controls.
- **Now Plating** — a bounded (~60) teaser of matches; a fast "does this look right?" sample.
- **Show all** — the full match set as a paginated browse shelf (reuses Discover's `_BrowseView`): small
  initial load reusing the teaser, then lazy DB paging; ordered alphabetically by title. A recipe is, in
  effect, a user-authored Discover shelf. The Recipe chip returns to the constructor (1-click back).

## 4. Interaction model (Phase 1 — building)

Each tag value cycles through states; **the connector word is the control**:
- `none` → **pool (or)** → **required (and)** → **exclude (not)** → `none`.
- The rail renders the connectors as live, clickable `or` / `and` words; excludes read as a distinct
  "and not …". Clicking a connector flips that value between pool and required.

## 5. Current presentation (DISPOSABLE — will be restyled in the UI/UX overhaul)

These are *not* contract; the overhaul may replace any of them as long as §1–§4 survive:
- Three-column constructor layout; chip/cloud visual styling and weight sizing; the plain-English rail
  wording and colours; the "Now Plating" / "Show all →" labels; card styling (shared with Discover).

## 6. Phase roadmap

1. **Phase 1 (now):** required + optional pool via clickable `or`↔`and` connectors; include/exclude state
   indication in the rail; engine emits one `EXISTS` per required value. *(Task #64.)*
2. **Phase 2 (deferred):** multiple independent OR-groups — `(Animated OR Anime) AND (Sci-Fi OR Fantasy)` —
   via **drag-ordered consecutive-AND clusters** (arrangement = parenthesization). Only needed for nested
   grouping; rare.
3. **Future:** weighted/scored ingredients (chips → sliders), dedup, recency decay, minimum-support floor —
   the superset that lets Recommendations fold in as an auto-authored recipe (parked; revisit at slice 4).
