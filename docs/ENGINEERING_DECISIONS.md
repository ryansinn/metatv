# MetaTV — Engineering Decisions

> **What this is.** A standing record of the non-obvious engineering choices in this
> codebase: what was decided, why, and which alternatives were weighed and set aside.
> It exists because the reasoning behind a choice evaporates faster than the code, and
> a reader who cannot see the reasoning cannot tell a deliberate trade-off from an
> oversight. Sibling of `docs/DESIGN_RATIONALE.md` (product/architecture decisions,
> DR-NNNN); this file covers implementation-level choices in the data, query and
> guard layers.

**How to read an entry.** Each is *Decision → Why → Alternatives considered*. Where a
choice rests on a measurement, the measurement is quoted with the shape of the data it
was taken on, so it can be re-run rather than taken on trust. The numbers below come
from the owner's live library: **492,697 channels**, 466,061 distinct names, ~334k keyed
movies, a 1.6 GB SQLite file.

**These are decisions, not laws.** Several were reversed once evidence arrived, and the
reversals are recorded in place. An entry that no longer matches the code is a bug in
this file.

---

## 1. Indexes first, and `ANALYZE` to repair what the indexes broke

**Decision.** Query performance is addressed with explicit composite and partial
indexes chosen per access path. `ANALYZE` **does** run — once, as a migration — and
`PRAGMA optimize` refreshes the statistics on close. Both ship.

**Why.** Statistics alone were worth nothing to the query that motivated the work.
Measured on a copy of the production database (492,511 channels), best of three:

| case | before | indexes only | + ANALYZE |
|---|---|---|---|
| default view (3 types) | 289.9 ms | **1.2 ms** | 1.1 ms |
| one media type | 244.3 ms | 1.3 ms | 1.2 ms |
| get_favorites | 182.7 ms | 0.5 ms | 0.5 ms |
| **get_by_category** | 145.9 ms | **487.4 ms** | **126.0 ms** |

`ANALYZE` on its own moved the channel-list query 221.6 ms → 222.9 ms with a
byte-identical plan: both candidate indexes matched nearly every row, so there was no
better plan for statistics to find. The indexes are what produced the 240×.

**But the indexes made `get_by_category` 3.3× worse** — a new index the planner chose
badly without distribution data. `ANALYZE` is what repairs that regression, and that is
the honest reason it ships: not to speed up the query the work was about, but to pay for
a cost the fix to that query introduced.

`PRAGMA optimize` on close re-analyses only what has drifted and costs 0.6 ms when
nothing has, which is almost every time. Without it the planner keeps reading statistics
written once, however many rows a catalogue refresh has since added.

**Alternatives considered.**

- *Indexes with no statistics at all.* Rejected: it is the `487.4 ms` column above. The
  regression is real and only distribution data fixes it.
- *`PRAGMA analysis_limit=1000` to bound the ANALYZE cost.* Rejected on measurement: it
  samples too shallowly to change the plans that matter, and saves little anyway — 10.0 s
  against 11.5 s — because the cost is reading 33 indexes, not counting rows.
- *A partial index `ON channels (name) WHERE is_favorite = 1`.* Rejected: it offers only
  a full-index SCAN, and a stat1-only planner prefers a SEARCH with an equality over a
  SCAN of any size. Keeping `is_hidden` as the leading column is what makes it a SEARCH.
- *Rely on `sqlite_stat4` for range/equality selectivity.* Rejected as non-portable:
  `stat4` requires `SQLITE_ENABLE_STAT4` at compile time. An index tuned against a local
  build with `stat4` behaved differently on CI's interpreters — a real divergence, caught
  when an index passed locally and failed on both CI runners. **A partial index expresses
  the same intent and is version-independent**, so that is the form used, and the shipped
  planner is treated as stat1-only.

> **Correction, 2026-08-28.** This entry previously stated the opposite — that the app
> does not run `ANALYZE` and does not ship `sqlite_stat1` — and was wrong on the day it
> was written; the work that added them had already merged. The error came from
> generalising a true measurement (`ANALYZE` did nothing for the channel-list query) into
> a false claim about the system (`ANALYZE` does nothing worth having), without
> re-reading the code. The live database carries 62 `sqlite_stat1` rows and 1,048
> `sqlite_stat4` rows, which is what a thirty-second check would have shown. Recorded
> rather than quietly rewritten, because this file's preamble makes the claim that an
> entry not matching the code is a bug in the file, and the first entry was that bug.

## 2. There is no directory map

**Decision.** `docs/ARCHITECTURE.md` was deleted rather than repaired, and no
hand-maintained structural map replaces it. Structure is read from the code;
`docs/DESIGN_RATIONALE.md` carries the why.

**Why.** The file described 621 modules in 76 hand-written lines. Measured before
deletion, it covered ~17% of `gui/` and ~35% of `core/`, named modules that no longer
existed, and omitted whole subsystems. It was also the file this project's guide sent
newcomers to first, so its errors were maximally load-bearing.

**A map that is confidently wrong is worse than no map**, because a reader has no way to
tell which third is accurate.

**Alternatives considered.**

- *Fix it and keep it.* Rejected: it had already been "fixed" before and re-decayed. A
  hand-maintained enumeration of a tree this size cannot stay true, and the failure is
  silent — nothing tells you the map has drifted.
- *Generate it from the import graph.* **Not rejected — deferred.** A generated map
  cannot drift, and that is the form to build if a map is wanted. What was rejected is
  a hand-written one.

This is one instance of a pattern that recurs below: *an enumeration never sees what
nobody remembered to add.* The same failure produced a stylesheet sweep that missed 838
call sites, a settings hook list missing a handler, and (below) two bulk writers missing
a lock retry.

---

## 3. Content identity is one stored key, tmdb-first

**Decision.** Cross-source dedup uses a single stored field, `content_key`, computed at
ingestion. It is `tmdb:{id}|{media_type}` when the provider shipped a TMDb id, else a
normalized title key — `{title}|{media_type}|{year}` for **movies**, and
`{title}|{media_type}` for series and live, which omit the year deliberately because
cross-provider year labels on a long-running series are noisy. Every figure quoted below
describes the movie form. Every collapse surface reads the stored
key; none re-derives identity.

**Why.** The same film appears many times across sources and language/quality variants.
Identity computed at read time would differ between surfaces — the channel list, Discover,
and the details pane would disagree about what is "the same title", which is visible to
the user as content appearing and disappearing. One stored field means one answer.

Tmdb-first because the provider often ships the id already, and where present it separates
productions the title/year key merges. Measured: the three *Aladdin* productions are
cleanly separated by id (`tmdb:812` ×19, `tmdb:420817` ×21, `tmdb:11238` ×13) while the
yearless fallback key merged 15 unrelated rows spanning a Disney animation, an anime, an
Italian romance and a documentary.

**Alternatives considered.**

- *Refuse to collapse without a year (yearless rows stand alone).* Weighed and open. It
  trades ~27,375 lost merges across 8,007 groups for zero false ones. Not chosen yet
  because the merges it would lose are mostly correct.
- *Use genre or provider category as a discriminator.* Rejected on data: only **18%** of
  yearless movie rows carry a genre tag, so the signal is absent for four rows in five.
  `collection` covers 86% but is the raw provider category and language-dependent
  (`Drammi/Romantici` vs `Drama / Romance` vs `Klasik Filmleri`), so comparing it raw
  would split genuine variants — the exact failure the coarse key exists to prevent.
- *Re-key user ratings on `content_key`.* **Rejected firmly.** The key flips to the
  `tmdb:` form when enrichment lands, which would orphan the row. Taste is collapsed at
  *read* on the stored key instead, so a title spanning several rows counts once.

### 3a. A writer maintains the invariant it breaks

**Decision.** Any code that writes `detected_tmdb_id` also recomputes `content_key` in
the same statement.

**Why.** These were previously separate migration steps ordered so the id landed first.
The ordering is not enforceable: the two are independently version-gated, and the id
backfill deliberately leaves its version unbumped when cancelled so it resumes on the
next launch — by which point the key step is version-satisfied and sits out. Every row
the resumed pass filled then carried an id under a stale key and stopped matching its own
variants. Silent, with no error and no failing test.

**Alternatives considered.** *Enforce the ordering at registration.* Rejected: it makes
correctness depend on two separately-gated tasks staying in a particular order forever,
which nothing checks. A writer that maintains its own invariant needs no ordering.

---

## 4. Guards are derived, never hand-listed

**Decision.** Invariants are enforced by checks that compute the population they cover —
from a function signature, an AST walk, or a token prefix — rather than by a list of names
a human maintains.

**Why.** Every hand-listed guard in this codebase's history has drifted, and the drift is
invisible: the list still passes, it just covers less than it claims. Concrete instances:
a theme sweep with 22 methods against 838 call sites, "completed" twice and broken both
times; a count that forwarded 22 of 25 filter axes; two of five bulk writers missing a
lock retry.

A derived guard has the property that **a newly added member is covered without anyone
remembering it exists**.

**Alternatives considered.**

- *Discipline and code review.* Rejected on evidence. The same set of invariants was
  measured twice on this codebase, two months apart: every one that shipped with a
  mechanical guard was still holding at zero, and every one left to discipline alone had
  regressed. Not some — every one, in both directions. That result is why guards here are
  mechanical rather than documented.
- *A linter alone.* Adopted where it fits (ruff), but insufficient: several invariants
  here are project-specific (which axes a count must forward; which token family a
  fixed-dark surface may draw from) and no general linter expresses them.
- *Regex-based guards.* Rejected after failure. A regex guard for stylesheet drift knew
  one syntactic shape and eleven real call sites had sailed past it; replaced with an AST
  walk that catches any expression reading the theme module.

**A guard must be proven able to fail.** Every guard here is mutation-tested: the
production behaviour is broken deliberately and the guard must go red. This has caught
guards that were structurally unable to detect their own subject — most recently, a
bulk-write check that only saw *direct* commits inside a loop and therefore stayed green
when the commit moved into a helper, which is exactly the refactor it was guarding.

---

## 5. Write concurrency is handled by WAL, a busy timeout, and per-batch retry

**Decision.** SQLite runs in WAL with `busy_timeout=30000` and `synchronous=NORMAL`.
Bulk write passes retry a locked batch through one shared helper. There is no serialized
write gateway.

**Why.** WAL lets readers proceed during a write, which removes most contention in an app
whose UI reads constantly. What WAL does not fix is a *long* transaction: a bulk backfill
holding a write for the length of a batch. That is the shape that actually failed
(observed 2026-08-01, a bulk `UPDATE` raising "database is locked"), and a bounded retry
addresses it directly.

Retry granularity is the **batch**, not the pass: a pass is a multi-minute full-table scan
on a 484k-row table, and restarting it on contention would turn a transient lock into
minutes of repeated work.

**Alternatives considered.**

- *A single serialized write gateway (all writes through one queue).* Rejected as
  disproportionate: it is new architecture across every committing method in the app
  (~80 by AST count under `metatv/`, of which the repositories hold about two thirds) to
  address contention that WAL plus a 30-second timeout already absorbs, when the one
  observed failure class is fixed by retrying five bulk paths.
- *Retry only the `commit()`.* Rejected as incorrect, not merely weak. A failed commit's
  rollback expires the session's in-memory changes, so a bare re-commit flushes nothing.
  The batch must be recomputed from a fresh query, which is why each retried batch owns
  its own `SELECT`.
- *`auto_vacuum=FULL` set unconditionally at startup.* Rejected after it caused a crash:
  run on a database that already had it, the implied `VACUUM` raised "database is locked"
  and bypassed `busy_timeout`. It is now applied only when the pragma is not already set.

---

## 6. Transparency counters report a floor, not an exact total

**Decision.** "N hidden by filters" is computed by comparing two capped result sets. When
both saturate the page cap, the UI shows `≥ 5,000` rather than a number.

**Why.** The counters exist so the user can see that content is being withheld and reveal
it. Before this, each counter was `len(comparison) - len(visible)` with both queries capped
at 5,000 — so when both saturated the difference was **zero**, and the reveal affordance
disappeared *exactly where the most was hidden*. A floor is honest at every input.

**Alternatives considered.**

- *Compute exact counts with a grouped query.* Rejected on measurement: the pair costs
  **414 ms** (215 + 198) in raw SQL on 484,287 rows, against a load that had just been
  taken from 252 ms to 1.1 ms, and up to three axes are measured per keystroke. An earlier
  3,028 ms figure for the same pair does **not** reproduce, and its attribution to the
  dead-stream `NOT IN` was wrong — that subquery costs ~17 ms. The conclusion survives at
  the lower number; the stated cause did not. Re-derive by timing the two `SELECT COUNT(*)`
  forms of the visible/comparison pair directly against the live database.
- *Raise the page cap.* Rejected: it moves the threshold without removing it, and costs
  memory on every load to fix a status line.
- *Materialise the full list to count it.* Rejected for the same reason as above — a
  second full scan for a number in a status label.

There is a known residual: a few exclusions are applied in Python after the query returns,
and a SQL `COUNT` cannot see them, so the figure can read slightly high when one is active.
Documented at the call site rather than hidden.

---

## 7. Wide signatures are addressed by deriving the forward, not by a parameter object

**Decision.** `get_all` takes ~37 filter axes as keyword arguments. Rather than replacing
them with a frozen query object, the *forwarding* between the query and its sibling
counters is derived from the accepting function's own signature.

**Why.** The problem a parameter object solves is call-site churn. Counting `get_all` /
`_apply_channel_filters` / `count_watched_matching` calls under `metatv/` by AST, the
distribution is roughly `{30:1, 28:1, 9:1, 8:2, 4:1, 1:10, 0:10}` — a couple of heavy
sites and a long tail passing at most one argument. (An earlier revision of this entry
quoted "19 of 26 pass a single argument" as a measurement; it was an estimate, never
counted, and does not reproduce. Re-derive with an `ast.walk` over `metatv/` matching
those three attribute names.)

That distribution is a weak argument on its own — with under a dozen real call sites, the
conversion would be an afternoon. **The decision rests on the second argument, not the
first: a parameter object would not have prevented the bug that actually occurred**,
which was a forward omitting fields, not a call site passing too many. The hand-copied
forwards are where drift happened: a count hand-listed 23 parameters and its caller hand-listed 22 more to feed
it — three enumerations of one axis set — and three axes had already gone missing, so a
row the list had dropped for a keyword was still reported as "hidden because watched".

**Alternatives considered.**

- *A frozen query object threaded through every caller.* Rejected on the distribution
  above. It would also not have prevented the observed bug, which was a forward omitting
  fields, not a call site passing too many.
- *`**kwargs` passthrough with no validation.* Rejected: it silently swallows a typo,
  which is how this class of drift hides. Unknown keys raise; axes that genuinely cannot
  apply are listed with their reason.

Related, same principle: `VisibilityScope` **is** a frozen bag of resolved exclusion sets,
used where the goal is one definition of "what is visible" shared by every surface. The
distinction is that it replaced *four divergent implementations*, not one wide signature.

---

## 8. Derived files resolve merge conflicts by rule, not by hand

**Decision.** `tests/code_health_baseline.json` — a generated snapshot of per-file line
counts — carries a git merge driver that resolves conflicts by taking the per-key maximum
of both sides.

**Why.** The file is derived, so every branch touching a tracked file rewrites it and any
two such branches conflict. The resolution was always mechanical, but a human had to
perform it: five rebases in one evening, each discarding a green CI run and restarting a
ten-minute two-platform gate.

Maximum is safe by construction: the ratchet is `max(1000, baseline)`, and each side's
value already passed on its own branch, so a limit at least as large as both cannot fail
either.

**Alternatives considered.**

- *Regenerate from the working tree in the driver.* This is the semantically correct
  answer and was rejected on mechanics: a merge driver runs *during* the merge, when the
  tree is not guaranteed to hold the final content of every path. A regenerated value that
  came out too low would reintroduce the false failure the driver exists to remove.
- *Stop recording shrinks.* Rejected: the shrink ratchet is the property that makes the
  guard useful, since it prevents a file from re-growing after a split.

Accepted cost: the resolution is slightly lax — a shrink recorded on one branch is lost if
the other kept a higher number. The next regeneration re-tightens it. **A driver that never
blocks and is occasionally loose beats one that is exact and stops the merge.**

---

## 9. A large repository is split by concern, using a mixin

**Decision.** `channel.py` is being reduced by extracting whole concerns. The first
extraction moved the ingestion/backfill write path (~1,000 lines) into a mixin that
`ChannelRepository` inherits, rather than into module-level functions.

**Why.** The prior extraction in this file (`channel_lens.py`) used pure module-level
functions, and that worked because a lens is a query over rows holding no session state.
Ingestion is the opposite: it commits in batches, retries locked writes, and calls its own
siblings. Converting it would mean rewriting ~1,000 lines of `self.session` into explicit
parameters — a large edit to code whose entire claim is that **it did not change**, where
every rewritten reference is a place behaviour can silently move.

A mixin moves the methods verbatim, and callers keep the same import. The pattern was
already present in the same class (`_ChannelStatsMixin`).

**Alternatives considered.**

- *Module-level functions taking `session`.* Rejected for this concern, for the reason
  above. Still correct for pure query code.
- *Splitting by line count to reach a target.* Rejected. The guideline number (1,000) is a
  prompt to look, not a verdict: a 1,400-line file doing one job needs no split, and a
  600-line file doing three does. The extracted module is comfortably over the guideline
  and coherent, so it is recorded in the ratchet baseline rather than split again. (No
  line count is quoted here on purpose: it moves with every change to the file, and the
  baseline is the place that tracks it.)

**The success criterion was chosen to be falsifiable**: the full suite must pass with no
assertion changed. Only import paths moved. Two classes of dangling reference appeared and
needed different tools to find — a static undefined-name check found three names that
`import` accepted and that would only fail when a method was called; the full suite found
two more (a lazy in-function import, and a module-level use) that no static check saw.

---

## 10. Names derived from provider data are computed once, at ingestion

**Decision.** Fields parsed out of a channel name — title, year, quality, region,
collection — are computed when the row is written and stored. Display and query code reads
the stored field and never re-parses.

**Why.** Re-parsing at render time means the same name can resolve differently in two
surfaces, and it puts string work in a paint path that runs per row. Storing also makes the
parse *auditable*: a wrong value is visible in the database rather than reconstructed.

The cost is that a parser change requires a re-parse pass over existing rows, so there is a
versioned migration whose bump triggers one.

**Alternatives considered.**

- *Parse at read time.* Rejected for the divergence and cost above.
- *Trust the trailing text after a year to be a subtitle unless ALL-CAPS.* Rejected on
  measurement. The heuristic held that provider junk is uppercase and title-case is part of
  the title. Across the library, **2,092 rows** in **478 distinct forms** had title-case
  trailing text, led by `sinhronizirano` (385), `Hallmark` (322), `Polski` (176) — dub
  markers, studios and languages. Those rows lost their year entirely and kept `(2021)
  Hallmark` inside the stored title.
- *Always strip whatever follows the year.* Rejected as over-correction: **383 of the 478**
  forms are singletons that may be genuine title text. The rule adopted extracts the year
  unconditionally (it is unambiguous wherever it sits) and removes the trailing text only
  when a classifier can name it. Unrecognised text stays in the title and still yields its
  year.

Verified across all 466,061 distinct names before shipping: 2,038 gained a year, **0 lost
one**, 0 lost a provider-appended cast credit.

---

## 11. A facet can have several values, with provenance and confidence

**Decision.** Facets (collection, language, genre, …) are stored as typed tags, many per
row, each recording the feeder that produced it and a confidence. Confidence ranks; it does
not suppress.

**Why.** In the guessing zone, recall matters more than precision: a facet the user cannot
find is worse than one ranked slightly wrong. Recording the feeder means a wrong tag can be
traced to the rule that produced it rather than argued about.

A worked case: a provider files a film under `CHRISTMAS` while its name says `Hallmark`.
Both are true. The provider's category is denoted (0.9); the name-derived one is a
recognised token (0.3), so it ranks below without being hidden — and a single title
carries both collections.

**Alternatives considered.**

- *One collection per row.* This is what the stored column does, and it is kept — for the
  provider's own category. What was rejected is treating that single column as the whole
  answer, since two independent feeders can each be right.
- *Suppressing low-confidence tags below a threshold.* Rejected: confidence is a ranking
  and prune-priority signal. A suppression gate would silently discard the adjacent guess
  that makes a facet findable at all.
