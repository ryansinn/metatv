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
