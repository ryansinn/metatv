# MetaTV — Design Rationale (Decision Log)

> **The "why" layer.** This is the human-facing record of *why* significant design and architecture
> decisions were made the way they were — the options weighed, the choice, and what was explicitly
> rejected and why. It is append-only: superseded decisions are marked, not deleted, so the reasoning
> trail survives instead of evaporating in chat.

## Where each kind of doc lives (the four-layer model)

A design concept gets recorded in up to four places, each answering a different reader's question.
Write a settled decision through them in this order; the flow is one-directional.

| Layer | Doc | Reader & question | Cadence |
|---|---|---|---|
| **Vision** (north star) | `docs/PRODUCT_VISION.md` | *Why does the product feel this way?* | Rarely changes |
| **Rationale** (the "why") | **`docs/DESIGN_RATIONALE.md`** (this file) | *Why did we decide it this way, and what did we reject?* | Append-only log |
| **Rules** (enforced invariant) | `CLAUDE.md` Critical Rules | *Claude: what must I never violate?* | Distilled from a decision |
| **Patterns** (how it behaves) | `docs/UI_UX_GUIDELINES.md` | *How does this interaction actually work?* | Per pattern |

**The habit:** a decision settles → write the *why* here → distill the enforceable *rule* into
CLAUDE.md / UI_UX_GUIDELINES → bump PRODUCT_VISION only if the north star actually moved. Don't
document a decision that hasn't been made; an entry may carry `Status: Proposed` until it's locked.

---

## Decision Log

### DR-0001 — The left sidebar is an instrument cluster of three *registers*, not a flat content stack
**Status:** Accepted in principle (2026-06-20). Open sub-decisions noted below.
**Ties to:** ambient-companion + forward-looking + landscape-first vision; chef (Recommendations) vs.
grocery (browse). **Rule to distill:** *every new sidebar section must declare its register.*

**Problem.** The left rail (a single vertical `QSplitter` of six `CollapsibleSection`s — Alerts,
Recommended, Queue, Favorites, History, Sources) feels over-saturated even though every item is
valuable. The real cause isn't "too many sections": it stacks **three different *kinds* of
information** in one column with no hierarchy, so they compete for the same vertical budget as if
they were peers.

**The three registers.**
1. **Live / prospective** — the system proposing actions, *changes on its own*: **Alerts, Watch
   Queue, Recommended**. (The watch/monitor-a-series feature is born here — it fires alerts.)
2. **Curated / retrospective** — stable libraries the user maintains, *change only when the user
   acts*: **Favorites, History**.
3. **System status** — not content at all, it's infrastructure: **Sources** (online/active state +
   the global show/hide filter).

**Organizing axis — why live-vs-curated, not frequency-of-use.** Frequency is the *symptom*; temporal
direction + agency is the *cause* (you check live things constantly *because* they change on their
own; curated things rarely *because* they're stable). Organizing by the cause yields a rule that
survives new features instead of one re-litigated each time — e.g. the series-monitor feature slots
deterministically into the live register with no debate.

**Analogy (cockpit).** The rail is an instrument cluster, not a content dump: **forward instruments**
(PFD/nav = Now & Next), the **logbook** (saved routes = the libraries), and the **annunciator/systems
panel** (always-on but compressed = Sources). A pilot doesn't fly by the logbook, and annunciators
stay visible but tiny. (Kitchen lens, in the product's own vocabulary: the *pass during service* vs.
the *recipe box* vs. the *walk-in / which supplier is online right now*.)

**Root thesis (the deeper framing).** The rail is a **launcher / index into deeper views, not a
content container.** Its job is quick-reference + quick-launch; *depth lives in the windshield views.*
This is the root the register model serves — saturation happened because rail sections tried to *be*
full content instead of *pointing* to it. Corollary: things you **browse** graduate to views; only
things that **inform or interrupt you in the moment** (Alerts, Recommended, Recent, compact Queue,
Sources status) keep a rail face.

**Decisions.**
- **Reorganize the rail by register**, not as an undifferentiated stack.
- **Split History by register — don't move it wholesale.** History has *two faces*: a **forward
  Recent / resume** use (jump back into the last thing after a crash/close; re-find something
  interesting that was never favorited/queued — a daily, low-friction, recency-ordered instrument)
  and a **retrospective archive** (the full log, stats, temporal patterns, self-reflection). Keep a
  lightweight **Recent** strip in the rail (*live* register — last ~N played, one-click resume), and
  **graduate the deep History archive to a main-area view** (the windshield space the context-engine
  / self-reflection surface needs — see ROADMAP "History as a context engine" and PRODUCT_VISION
  "The mirror"). History-as-evidence is the *inference* engine's other half: Recommended is the
  *inference* end, History the *evidence* end — twins.
- **Sources becomes an always-visible collapsed status strip** above Settings: a one-line summary
  (e.g. `3 sources · 2 online · BiggyJuke active`) that expands to per-source toggles + the filter.
  **Not a tab** — its value is *ambient* (real-time status + filter), which a tab would hide.
- **Every new sidebar section must declare its register**; browse-libraries graduate to views.
- **Decompose Alerts — it bundles two registers.** `WatchAlertsSection` mixes **Watch Alerts** (EPG
  watchlist firing — *live/content*, high value, keep a compact rail face) with **stream
  monitoring/retry** (`stream_retry_manager` — *system/diagnostic status*, not content). Bundling them
  over-saturates the section (the sidebar's root problem, one level down). Demote stream-monitoring to
  **status treatment** (compact count → expand on demand, in the systems register *with* Sources) and/or
  a diagnostics view, with **aggressive cruft auto-prune** — low LIVE-stream availability guarantees
  constant retry noise, so assume noise: TTL/cap stale entries rather than displaying every one. Don't
  remove it (serves a real reactive need); stop it occupying prime ambient space and accumulating. This
  is also the targeted prep that makes room for **monitor-a-series alerts** to land in Watch Alerts.

**Refined (2026-06-20, from daily-use feedback).** The first cut called History *purely retrospective*
and graduated it wholesale. Real daily use corrected that — History is also a **forward** instrument:
(a) resume after a crash/close without a lot of clicks; (b) a safety net for interesting items browsed
past but never favorited/queued (the watch queue itself gets unruly — things added on past days get
lost in the middle); (c) **re-joining an ongoing live event** (e.g. the World Cup on one channel —
never favorited or queued, just re-clicked from History to catch the latest). Note (c) shows the
resume semantics differ by media type: VOD resumes at position, **live re-tunes to the channel's
*latest***. Resolution: split History by register (Recent strip in the rail + deep archive as a view),
mirroring how Sources resolves (compact status strip ↔ full expand). The mistake was treating History
as one thing.

**Emerging pattern (2026-06-20).** Each rail section is shaping up to have *two faces*: a **compact
rail face** (the forward instrument) and a **rich windshield face** (a full main-area view reached by
a bottom-row chip). The windshield faces should **reuse the Discovery shelf/card layout** — posters,
shelves grouped by category/tag — rather than reinvent a list per collection (reuse-before-reinvent;
self-documenting modularity). The `discover_shelf` / `discover_card` / flow-layout widgets are a
**reusable collection-browse surface**, not Discovery-specific: a full **Watch Queue** view (shelves
by category, proposed as a `Queue` chip), the **History archive**, and possibly **Favorites** all
render through it. Caveat: a collection with intrinsic *order* (the VOD queue's "what's next") needs an
**Up-Next** ordered lane alongside the category shelves so spatial grouping doesn't bury the next item;
live-follow content doesn't queue at all (live-vs-VOD again). **Build-sequencing caveat: don't build
these views now** — perfect the shelf UX on the *Discover* proving ground first, then replicate the
stabilized surface (see **DR-0002**).

**Rejected.**
- *Organize by frequency-of-use* — symptom, not cause; would re-litigate every new feature.
- *Graduate History wholesale to a view* — it has a real daily forward/resume face that belongs in the
  rail (see Refined, above); only the deep archive graduates.
- *Put Sources in a second tab* — hides the always-on status/filter whose entire worth is being visible.

**Resolved (2026-06-20).**
- **Favorites is *not* privileged in the rail.** Real use: the user doesn't use sidebar Favorites at
  all. Under the launcher thesis, a purely *curated* collection has little reason to occupy rail
  space — it **graduates to a windshield view** (a Discovery-shelf collection, like Queue/History),
  reachable when wanted. Revisit a minimal quick-launch entry only if it later earns one.

**Method note.** This entry exemplifies the product's #1 principle (*function over form, elegance
earned*): the rail was built the practical way first; its true **shape and relationships**
(launcher-not-container, registers, two-faces, live-vs-VOD) became legible only through daily use, and
this log formalizes them *as they emerge* — not designed top-down up front.

**Open (lock before implementation).**
- **Live-follow** — its own surface, or just let the Recent strip do it? Lean: Recent does it for now.
- **Sequencing** — light rail reorg first (so the series-monitor lands in a clean rail), or build the
  feature into the current stack and reorganize after. Lean (refined — see DR-0002): **feature-first** —
  build monitor-a-series on existing surfaces; defer the rail reorg, and defer the full collection
  views until the Discover shelf UX has stabilized.

---

### DR-0002 — Perfect one view, then replicate — don't standardize a moving target
**Status:** Accepted (2026-06-20).

**Principle.** Full-scale view components (the Discovery-shelf collection surface, and the windshield
"faces" of rail sections — full Queue, History archive, Favorites) are **deliberately not built all at
once.** The look / feel / behavior of a shelf-style view is still being actively refined; if five views
already consumed that surface, every UX tweak would mean touching five places — or worse, an immature
abstraction would get frozen across all of them. Instead: **dive deep on a single canonical view,
perfect its experience and style, let it stabilize, then extract the proven surface and replicate it**
across the other contexts.

**The proving ground is Discover** — the view under active refinement, so where the shelf/card UX gets
perfected. History / Queue / Favorites views come *later*, by replicating the stabilized surface, not
by being built in parallel now.

**Reconciles with reuse-before-reinvent (complementary, not contradictory).** Reuse-before-reinvent
forbids *divergent parallel copies of a stable primitive*; this principle governs *when* to extract the
shared abstraction — **after** the UX stabilizes, not before. Sequence: build one well → stabilize →
extract → reuse. Premature *duplication* of a proven primitive and premature *abstraction* of a moving
target are both anti-patterns; both multiply churn. Avoid both.

**Consequence for current work.** Don't build new full-scale views now. monitor-a-series lands on
existing surfaces (Alerts / rail); the collection views (DR-0001 "Emerging pattern") wait until the
Discover shelf UX is proven. This is the product's #1 principle (function-first, elegance earned)
applied to *build sequencing*, and the timing complement to the "Reuse before reinvent" rule in
CLAUDE.md.

---

### DR-0003 — Discovery vectors: keep Similar Titles *crude*; add a metadata "Similar Content" sibling; both distinct from global Recommendations
**Status:** Accepted (2026-06-20, user steer). **Supersedes** an earlier ROADMAP/Vision framing that
called title-string matching "spurious collisions / noise to fix."

**Decision.** Do **not** "upgrade" Similar Titles into metadata similarity — its crude title-string
linkage is a **feature.** Instead expose **three distinct discovery vectors**, never collapsing one
into another:

| Vector | Anchor | Link type | Character | Surface |
|---|---|---|---|---|
| **Recommendations** | *you* (taste profile) | metadata + your weights | global, personalized, comfort — "more of the same essence" | sidebar / dashboard |
| **Similar Content** (NEW) | *this item* | metadata (genre/cast/director/TF-IDF) | contextual — "things like THIS in essence" | details-pane section |
| **Similar Titles** (exists) | *this item* | crude title-string | contextual, lateral, explore — "totally different, one thread" | details-pane section |

**Why crude title-linkage is a feature (not a defect).** Metadata similarity is "biased or dumb" — it
returns *more of the same* (the echo chamber). A weak, almost-random shared-title link (`Park` → South
Park / Jurassic Park / Linkin Park) jumps *across* genres/styles to surface something genuinely novel.
That looseness is the **anti-filter-bubble mechanism** and a concrete expression of *a mirror, never a
cage* (PRODUCT_VISION #8). Homogenizing it into metadata would collapse it into a worse Recommendations
and destroy its value.

**The mechanism is calibrated juxtaposition** — *near-random content that still feels relatable.* The shared title token is *just enough relevance* to
make the cross-genre jump feel connected (not random noise), while the genre jump is *just enough
novelty* to make the brain curious — the Goldilocks zone between "totally random" (no hook, no
engagement) and "more of the same" (no spark, no curiosity). That is precisely why **neither pure
randomness nor metadata-similarity can substitute**: one has no thread, the other has no surprise.
**Real-use evidence:** Similar Titles has surfaced substantial content the user would *never* have
searched for or browsed to find.

**Two contextual lenses, by design.** Similar Content and Similar Titles are *both* anchored to the
current item (the micro / right-pane discovery vector) but use different links, so they return
**completely different result sets** — and the **contrast itself is informative** (crude-vs-essence
neighbors of the same title). Recommendations is the third, *global/personalized* vector — don't fold
the contextual two into it either.

**Distinct from dedup (don't conflate).** Crude title-matching is *good for Similar Titles* but *bad
for dedup* (it false-merges different productions → the South-Park wrong-episode-count bug). Canonical
`tmdb_id`/`imdb_id` work belongs to **Recommendations + Similar Content + dedup**, **not** to flattening
Similar Titles. Same mechanism, opposite desirability by goal.

**Consequence.** The rabbit-hole drift (resemblance dissolving as you hop Similar Titles) is the
*intended* payoff, not noise. A breadcrumb stays useful for *legibility + reversibility*, but a "just a
shared word" hop is the feature working.

---

### DR-0004 — Minimize clicks: prefer scroll / progressive disclosure over tabs & drill-down
**Status:** Accepted (2026-06-20, user steer — *"a key feature of the app"*).

**Principle.** Click-economy is a **first-class feature**, not polish. Prefer **continuous low-friction
reveal** (scroll, progressive disclosure, in-place expand) over **click-gated navigation** (tabs,
drill-down, modal stacks) that forces users through "clicking layer hell." Every avoidable click is
friction between the user and their content, and the ambient-companion loop dies by a thousand clicks.

**Applied decisions (this is why several other choices look the way they do).**
- **The details pane *scrolls*, it does not tab.** Every section (metadata, plot, cast, the
  Similar-Titles / Similar-Content adjacency sections — DR-0003) is reached by scrolling *one* surface;
  nothing is hidden behind a tab click. One gesture reveals everything.
- **The rail is a one-click launcher** (DR-0001), not a place you drill into; libraries graduate to
  views rather than nesting. A *second sidebar tab* was floated during DR-0001 and **deliberately not
  adopted** — it would have re-introduced exactly the click-gating this principle forbids.
- **Adjacency navigation uses an overlay whose *close* is the back** (DR-0003) — no back-button chrome,
  no extra drill-down.

**Caveat (not absolutist).** The test is **total interaction friction to the user's goal**, not a
literal click count. A control that genuinely *reduces* total friction — a chip that jumps straight to a
view you'd otherwise scroll forever to find — still serves the principle. The enemy is *layered
hunting*, not the existence of buttons. Distill into a CLAUDE.md UI rule once a second surface needs it.

---

### DR-0005 — Everything is a *tag*: unify attributes, views, and filters into one composable query over a tag corpus
**Status:** Accepted in principle (2026-06-21, user steer). The **model** and the **storage shape** are
decided; schema-level sub-decisions (namespace cardinality, the rule definition shape, the exact
derived-cache mechanism) are open and will be locked during implementation.

**Context — the schema sprawl is N names for one idea.** Content today carries a pile of parallel,
hand-authored columns: `detected_prefix`, `detected_region`, `detected_quality`, `detected_year`,
`detected_title`, plus `genre`, `category`, `user_category`, `is_adult`, and friends. They are all the
*same shape* — a value, in a group, attached to a channel — yet each is its own column, its own
detection code, its own filter axis, its own bespoke UI. Worse, re-running detection
(`update_detected_prefixes`) **overwrites the columns in place**: there is no separation between *the
machine guessed this* and *the human asserted this*, so improving the rules risks trampling user
curation. And the things built *on top* — the two-tier filter, the Discover genre/decade shelves, the
Categories, the recommendation "attribute weights" — are parallel systems doing the same job by
different names. We kept adding "different names for the same thing" (user's framing) instead of naming
the thing.

**The decision has three parts.**

**1. The thing is a tag.** Model every attribute as a **tag** = `(namespace, value, canonical_id)` —
`region:US`, `quality:4K`, `genre:drama`, `lang:en`, `content_type:adult|movie|live`, `decade:1980s`,
`user:cozy-saturday`. A channel↔tag link (`ContentTag`) carries a **provenance**
(`source ∈ {generated, user}`) and, for generated tags, the **rule + version** that produced it. The
detection logic (prefix/suffix/regex on the name, `raw_data` field maps, metadata-derived) generalizes
from hardcoded column-writers into **versioned rules that "massage content into qualifying" for a tag**
(user's words). Cross-language/alias unification (Drama/Drame/Dramma/دراما → `genre:drama`; EN↔MULTI;
region codes) is just **tag canonicalization** — many surface aliases resolving to one `canonical_id`.

**2. Tags are the single source of truth; the fast columns become a *derived cache*.** The trap: the
current sprawl is *fast* precisely because it is denormalized — `WHERE detected_prefix IN (…)` is an
indexed scan over 1M+ channels, whereas a pure M:N tag table (≈5–10M rows) turns the hot multi-facet
filter ("drama AND 4K AND english from an active source") into an intersection / `GROUP BY HAVING`.
**Chosen reconciliation (user, 2026-06-21): hybrid.** Tags are canonical (with provenance,
reprocessable); the denormalized fast-filter columns/bitmap are a **generated index derived from
tags**, regenerated when tags change — *not* hand-authored schema. This answers the real complaint (you
stop *authoring* `detected_*`; they become an index, like a search index) while keeping filter latency.
*Rejected: pure tags-only / fully-normalized* — conceptually cleanest but regresses the hot path without
a heavy indexing/caching strategy; the hybrid gets the clean model **and** the speed.

**3. Views, filters, and shelves are all one query (the keystone — user steer).** Once content is
tagged, **a View is just a saved preset tag-predicate plus a presentation**: "Movies" =
`content_type:movie`; "Sports" = `genre:sports`; "Live" = `content_type:live`; EPG = "has guide data";
Favorites/History = engagement tags; a user's "Cozy Saturday" = `user:cozy-saturday`. **The filter
panel is a bolt-on modifier** — transient predicates AND-ed onto the *current view's base predicate*,
not a separate system. **A Discover shelf is a group-by over a tag namespace.** User-created
views/shelves are just **saved predicates**. So Views + Filters + Shelves + Categories collapse into one
primitive: **(base predicate) ∘ (modifier predicates) → over the tag corpus → (presentation)**. This is
the same one-chokepoint instinct as the rest of the architecture, applied to *navigation itself*.

**The contract that makes reprocessing safe (user requirement).** **User tags are sacred; generated
tags are disposable.** Reprocess = `DELETE ContentTag WHERE source='generated'` → re-run the rules;
user assignments are never touched. As the rules improve, scrub-and-reapply the entire generated layer
at full fidelity, and the user's curation survives intact. This is strictly better than today's in-place
column overwrite, and it is the reason the work pays for itself.

**What this unifies / supersedes.** It folds the two-tier filter axes, the `detected_*` authored
columns, Categories/`user_category`, the Discover facet shelves, `content_dedup` canonicalization, and
the recommendation engine's "attribute weights" (tags *are* the attributes) into one model. It does
**not** discard them — most become either *rules that emit tags* or *queries that read tags*. Genre
unification (**D5**, in flight) is deliberately the **first canonicalization rule** — the pilot that
seeds the alias layer. (Note: `normalize_genre()` / `_GENRE_NORM` already exist in
`repositories/channel.py`; D5 is wiring that existing canonicalizer into the Discover shelf path, which
is exactly the tag-alias pattern in miniature.)

**Sequencing (user steer, 2026-06-21): structure before skin.** Resolve the functional architecture —
tags, the view/filter/shelf query model, and the layout/interaction design — **before** any visual
reskin / "modern look." Reskinning a moving structure is wasted motion (echoes DR-0002 — *don't
standardize a moving target* — and the function-over-form north star). The reskin is a *later, separate*
effort layered on a settled structure, not interleaved with it.

**Phased, no big-bang (detail in ROADMAP).** D5 pilot → lock the schema (Tag / ContentTag / namespace
cardinality / rule versioning / the reprocess contract) → **shadow-build** the tag store + rules engine
by *deriving* tags from today's `detected_*` + `raw_data` (nothing cuts over) → migrate read surfaces
one at a time (filter → Discover → details → recs) with the columns kept as the derived cache → user
tags + the scrub-and-reapply loop → retire the redundant authored columns (or keep them purely as the
cache). Distill the enforceable invariants (the provenance rule; "reads go through the tag query, not
bespoke columns") into CLAUDE.md **once the schema is locked**, not before.

**Open sub-decisions.** Namespace cardinality (is `quality` single-valued, or can a channel be both
`HD` and `HEVC`?); the rule-definition shape (declarative table vs. code); the exact derived-cache
mechanism (keep `detected_*` columns vs. a per-channel tag-id bitmap / inverted index); how the current
filter's `is_filtered` / no-data-passthrough semantics map onto tag predicates; whether saved user
views live in `config` or the DB.

**Refined / extended (2026-06-21 design session).** Six clarifications that sharpen the model:

1. **Config is *disposable*; curation lives in the DB.** The litmus test for *where* a value belongs:
   you should be able to `rm config.yaml`, relaunch, and lose at most a few minutes of re-setting
   preferences — never any actual *work*. If deleting it would lose something you'd be upset about,
   that thing is mis-homed. **Stays in config** (settings whose loss is a mild annoyance): environment/
   paths, the playback engine, app-behaviour toggles, **UI chrome** (splitter/panel sizes, collapse
   state, zoom, theme, sidebar order), and app-state markers (What's-New cursor, migration versions).
   **Moves to the DB** (curation — loss is real work): global exclusions, user categories,
   monitored-series alerts, the EPG watchlist, and the Discover shelf-zone layout. The axis is **not**
   "user-set vs. default" (splitter sizes are user-set but trivial) — it's *"does losing it hurt?"* This
   is *why* the exclusion-wipe incident hurt: precious curation was living in a wholesale-rewritten YAML.
   The first curation-to-DB slice is **global exclusions → `source=user` tags**, which makes a wipe like
   that *structurally impossible* (row-level writes, no whole-file rewrite).

2. **"Type" is the user's word for *namespace*; each tag is single-type.** A tag *is* `type:value`, so it
   belongs to exactly one type — **one type → many tags**, never a multi-typed tag. The
   "could a tag be several types?" intuition actually lives in **cross-type *relationships*** (a compound
   locale `UK-NOWTV` implies a region *and* a platform; a region can imply a language) — links **between**
   single-type tags, not multi-typing. Single-type tags are what keep filtering/grouping unambiguous.

3. **Select-All is *per type*.** Because types are **orthogonal axes**, one Select-All spanning them
   (exclude platforms *and* languages at once) is a category error. The correct shape — which falls
   straight out of (2) — is each **type** rendered as its own group with its own Select-All + count. The
   cross-type select-all disappears; this is how the exclusions/filter UI renders once it's tag-native.

4. **One background-ops progress surface.** The Migration Center (visible, cancellable, multi-task
   progress panel) is not migration-specific — **source add/refresh is the same shape** (a long
   background pass over the corpus) and routes through the same panel. The tag-reprocessing loop is just
   another task on it.

5. **`##...##` provider headers are a tag source — a `collection` type.** The provider-injected
   category headers (`### WOW SPORT ###`, `#### BAMBINI HD/4K ##### · UHD`) are organizational markers
   whose *rows* are junk (bumper streams — skipped at load) but whose *labels* are gold: a
   provider-defined grouping. The stateful loader **already** propagates the label to the channels
   beneath it (`source_category`) and splits embedded quality markers into `source_quality_flags` — so
   those two columns are the **pre-tag denormalized shadow** of a generated **`collection`-type tag** +
   **quality tags**, applied by the hash-header rule (`source=generated`, scrub-and-reapplied). They need
   the same **canonicalization** as genres (noisy labels; the same collection spelled differently across
   providers) — i.e. another instance of D5's pattern. "Collection" is thus one of the predicted
   "other types." Net: **discard the header row, keep the label as a tag.**

6. **Canonicalization unifies *spellings*, never *concepts* — store the truth, group at presentation
   (genre de-pollution).** Wiring the existing `normalize_genre` into Discover (D5) exposed that the
   `_GENRE_NORM` table did two different jobs: legitimate cross-language/spelling unification
   (`Drame`→`Drama`, `Science-Fiction & Fantastique`→`Sci-Fi & Fantasy`) **and** illegitimate
   *concept-merging* that folded pure forms into compounds (`action`→`Action & Adventure`,
   `science fiction`/`fantasy`→`Sci-Fi & Fantasy`). The decision: **keep them distinct.** The litmus is
   *perceptual* — "a viewer knows it when they **sees** it": **Fast & Furious is `Action`; Indiana Jones
   is `Action & Adventure`** — the adventure element is felt, not decorative. So unify only what looks
   identical (mechanical spelling/locale); never merge what *feels* different. The deciding engineering
   argument: **merging is lossy and irreversible, keeping-distinct is not** — from distinct tags you can
   always compute the union at the *presentation* layer (a "Sci-Fi & Fantasy" shelf = the predicate
   `tag ∈ {Sci-Fi, Fantasy, Sci-Fi & Fantasy}`), but from a merged bucket you can never recover the pure
   set. Crucially, the app must **never *invent* a tag the source didn't assert**: we do not split the
   `Sci-Fi & Fantasy` compound into two tags and stamp both onto content (that would drop pure-Fantasy
   GoT into a SciFi bucket). The source's compound is a legitimate, source-defined general bucket; what's
   forbidden is the *app* manufacturing the association. (Empirically the current corpus is ~all TMDb-TV
   compounds — 0 pure `Science Fiction`/`Fantasy`, 494 `Sci-Fi & Fantasy` — so de-pollution costs nothing
   today and only prevents future mis-tagging once richer metadata distinguishes them.) Open: separating
   pure SciFi from Fantasy at all needs metadata that *has* the distinction (TMDb **movie** genres 878 vs
   14; this provider serves the TV-combined genre) — a TMDb-provider-integration item, not a table edit.
