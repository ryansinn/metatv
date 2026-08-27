# Audit rebuttal — 2026-08-27

Findings from the external audit (`docs/` artifact, 2026-08-27) that were **tested and
rejected**, or **accepted with a correction**. Every entry states what was measured and how,
so a later re-audit can check the reasoning rather than repeat it.

Findings not listed here were accepted and are either fixed or on the remediation plan.

**Why this file exists:** the audit was produced by a reviewer instructed to be adversarial and
to treat the repository's own documents as testimony rather than evidence. That produced several
correct findings that nothing else had surfaced — and a handful of confident claims that do not
survive measurement. Keeping the disagreements written down means the next audit argues with the
evidence instead of restating the first one.

---

## R1 — "`ANALYZE` is the cheapest fix in the entire audit" — REJECTED AS STATED

**The claim.** No `sqlite_stat1` table exists, so every query plan is chosen from SQLite's
built-in guess of ~10 rows per indexed equality; running `ANALYZE` is one line and every prior
performance measurement is invalid without it.

**What was measured.** A byte-copy of the 1.6 GB production database, the channel list's hottest
query, best of three after a warm-up:

| | time | plan |
|---|---|---|
| no statistics | 221.6 ms | `SEARCH ... USING INDEX ix_channels_is_hidden` + temp b-tree sort |
| after `ANALYZE` | 222.9 ms | **identical plan** |

`ANALYZE` cost 10.3 s on first run and changed nothing.

**Why the claim fails as stated.** Statistics let the planner choose a *better* plan. There was no
better plan available:

```
is_hidden = 0          492,510 of 492,511 rows
media_type = 'movie'   334,318 rows
```

Neither index discriminates. The query is a large scan plus a sort either way. The audit reasoned
from "no statistics ⇒ wrong plans" without checking whether a better plan existed to be chosen.

**What actually fixes it.** Composite indexes covering the filter *and* the sort. Two, not one —
`(is_hidden, media_type, name)` cannot order a query that fixes only `is_hidden`, because that
leaves the index ordered by `(media_type, name)`:

| case | baseline | + indexes | + indexes + `ANALYZE` |
|---|---:|---:|---:|
| movies, first page | 251.8 ms | 1.2 ms | 1.1 ms |
| movies, deep page | 605.2 ms | 4.7 ms | 4.0 ms |
| no media type | 260.6 ms | 1.1 ms | 1.0 ms |
| `count(movies)` | 181.2 ms | 10.3 ms | 10.0 ms |
| provider + movies | 227.7 ms | 1.5 ms | 1.3 ms |
| search "star" | 279.4 ms | 12.7 ms | 12.5 ms |
| **favorites** | 189.8 ms | **343.6 ms** | **0.5 ms** |

Measured through the real repository, best of three, on a copy of the production database.

**And here the audit's instinct turns out to be half right, for a reason it did not give.** Look
at the Favorites row. Adding the indexes made that query **1.8× slower**, because
`ix_channels_hidden_name` lets SQLite skip a sort of 28 rows by walking all 492,511 in name order
— which, with no statistics, looks like a bargain. With statistics the planner knows
`is_favorite = 1` is rare, takes the 28-row index, and the same query runs in 0.5 ms.

So: `ANALYZE` alone is worth nothing here, and `ANALYZE` becomes **mandatory** the moment the
composite indexes land. Not the cheapest fix in the audit; the necessary second half of the real
one. `PRAGMA analysis_limit` was tried and rejected — at 1000 it samples too shallowly to learn
that `is_favorite = 1` is rare, so Favorites keeps the bad plan (378 ms), and it saves little
anyway (10.0 s against 11.5 s), because the cost is reading 33 indexes rather than counting rows.

**Disposition.** Both halves ship together in `QueryIndexTask`, off the UI thread through the
existing migration framework, with `PRAGMA optimize` on close (0.6 ms) keeping the statistics
current as the catalog changes.

## R2 — "Keep `docs/ARCHITECTURE.md` and fix its false claim" — REJECTED, went further

**The claim.** The file is stale (covers ~17% of `gui/`, names deleted modules); keep it and
correct the "no UI dependencies" line.

**Why it fails.** It was **76 hand-written lines describing 621 files**. The per-file format is
*what made it unmaintainable*, so a corrected version decays on the same schedule. It was also
the file `CLAUDE.md` sent newcomers to first, which makes confidently-wrong worse than absent.

**Disposition.** Deleted (#495). `CLAUDE.md` now records *why there is no map*, so it does not get
helpfully recreated. Supporting evidence: the ADR log is the largest document in the tree at 762
lines and has not rotted, because it records decisions rather than structure. Nobody maintained
either one.

---

## R3 — "`content_key` merges films that are not the same film" — ACCEPTED WITH A CORRECTION

**The claim.** Identity is a heuristic producing wrong merges: The Office US/UK collide, two
different films named *Crash* collide, an empty year makes a separate group.

**All true, and reproduced.** But the finding conflates two defects with very different weights:

- **The merges are visible and rare.** A user sees one row where two were expected and can tell
  something is wrong. Format remakes are a small share of a 492k-row catalogue.
- **The per-row key flip is invisible and continuous.** Enrichment flips one variant's key while
  its sibling keeps the old one; they stop being siblings mid-flight; and the recommendation
  engine collapses taste on that key, so one title's genre weight counts twice. No error, no log
  line, no failing test — the previously-shipped fix for this silently reopened.

**Disposition.** The flip is prioritised (remediation step 8). The merges get a cheap fix — use
year for series only when both rows have one and they differ by more than two, preserving the
"don't split on noisy provider years" property that motivated dropping year in the first place.

---

## R4 — "Install ruff and delete the hand-written guard code" — ACCEPTED, BADLY UNDERSTATED

**The claim.** ~1,866 lines of AST-walking pytest guards exist because there is no linter; install
one and move the rules into it.

**Correct in direction.** Wrong about the cost, in three ways found by doing it:

1. **Default rules are unusable.** `ruff check` reports 5,892 findings. 2,473 are the codebase's
   normal string style, 376 object to the changelog filename convention, and 812 of 827
   undefined-name hits are one file's deliberate runtime token rebinding. The curated set is ~600.
   *Configuring it is the work*; installing it is not.
2. **`--fix` was unsafe.** It silently deleted **30 deliberate re-exports** across 13 modules and
   broke test collection. Two carried a literal `# re-export` comment, which no linter can honour.
   Fixed in #498 by repointing 26 test imports and declaring the 3 real facades in `__all__`.
3. **Not all guards can move.** The three that measure *semantics* — WCAG contrast on stylesheets
   reconstructed from the AST, painted geometry, palette distinctness — have no lint equivalent.
   Roughly 600 lines of pure-grep guards can move to ruff; the measuring ones must stay.

**Also rejected within this finding:** the suggestion to enable a naive-datetime rule as
"encoding the project's own EPG rule". It contradicts it. This codebase stores `start_time` /
`stop_time` UTC-naive *deliberately*; the rule reports 303 findings against intentional design and
its prescribed fix would break the storage contract. The rule the project wants — "go through
`epg_utils`" — is adjacent and needs a project-specific guard.

---

## R5 — "`auto_vacuum=FULL` is very likely the root of the provider-delete freeze" — UNVERIFIED

The audit flags this as a design question rather than a proven defect, and states it could not
measure it. Recorded here so a re-audit does not promote it to a finding without evidence. It
remains plausible and unmeasured.

---

## Standing corrections to the audit's own figures

- **34 re-exports** was the first count; **4 of those are aliased imports the module actually
  uses** (`_to_qcolor`, `_no_width_force`, `_DEFAULT_HEADERS`, `_MiddleElideLabel`). Real count 30.
- The **"~94% behavioural tests"** figure has not been independently verified. Recorded as the
  auditor's measurement, not as confirmed.
