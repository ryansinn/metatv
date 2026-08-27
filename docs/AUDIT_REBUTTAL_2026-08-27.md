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

## R1 — "`ANALYZE` is the cheapest fix in the entire audit" — REJECTED

**The claim.** No `sqlite_stat1` table exists, so every query plan is chosen from SQLite's
built-in guess of ~10 rows per indexed equality; running `ANALYZE` is one line and every prior
performance measurement is invalid without it.

**What was measured.** A byte-copy of the 1.6 GB production database, the channel list's hottest
query, three runs each after a warm-up:

| | time | plan |
|---|---|---|
| no statistics | 221.6 ms | `SEARCH ... USING INDEX ix_channels_is_hidden` + temp b-tree sort |
| after `ANALYZE` | 222.9 ms | **identical plan** |

`ANALYZE` cost 10.3 s on first run (then 0.0006 s) and changed nothing.

**Why the claim fails.** Statistics let the planner choose a *better* plan. There was no better
plan to choose:

```
is_hidden = 0          492,510 of 492,511 rows
media_type = 'movie'   334,318 rows
```

Both indexes are useless as discriminators. The query is a large scan plus a sort either way. The
audit reasoned from "no statistics ⇒ wrong plans" without checking whether a better plan existed.

**What actually fixes it.** One composite index covering the filter *and* the sort:

| | time |
|---|---|
| 33 single-column indexes | 202 ms |
| `+ (is_hidden, media_type, name)` | **0.0 ms** |

6,683× for a 0.7 s index build, because SQLite walks the index in `name` order and stops at 50
rows instead of sorting 334,000.

**Disposition.** `ANALYZE` is demoted from step 1 to hygiene, and belongs in a background
migration task rather than at startup — a 10 s first-launch cost for no measured benefit.
`PRAGMA optimize` on close is worth keeping at 0.0006 s. The composite indexes are the real work.

---

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
