# Design index — where the settled decisions actually live

**Read this before designing anything.** A view, a row, a placement, a naming
scheme, a priority rule: check here first, then read the artifact.

## Why this file exists

The design decisions for this project live in **artifacts**, not in the
repository. Nothing in the code links to them, so a reader — human or agent —
can work through the whole tree and never learn they exist. That is not a
theoretical gap:

- 2026-08-31, twice in one session, a from-scratch design was produced for work
  that was already settled. The owner: *"we redid the entire interface, it's in
  the artifact. are you not referencing the artifact on how to build this?"*
  and later *"I'm not even going to read through the rest of this artifact until
  you review the existing artifacts that cover all of this work."*
- Worse than duplicated effort: **code shipped that contradicted a settled
  decision.** The recording engine was built so recordings never interrupt
  playback, with a written rationale defending it, when the settled answer was
  *"warn and take, with a countdown"*. It also froze the stop time at schedule
  time, which the spec forbids in as many words because a running recording can
  be extended. Both were found only when the owner pushed back.

`Artifact action:"list"` enumerates them, but only if you think to run it. This
file makes the mapping greppable from inside the repo, which is where the
question actually gets asked.

## How to use it

1. Find the topic below.
2. Read the artifact — **the "Settled — <date>" blocks first**. Those are
   decisions, not proposals, and they are not yours to re-open.
3. If a settled answer looks wrong, say so in one line and build it anyway.
   That is a disagreement to raise, never one to quietly design around.

## The index

| Topic | Artifact | Holds |
|---|---|---|
| Watch-list matching · downloads · recording | **Catch, Keep, Record** | The settled answers for all three. Whole-word matching, folder layout, naming template, the free-space floor, "warn and take" with the countdown, signed padding offsets, live extend, watch-while-recording, `Downloads/` and `Recordings/` side by side. |
| Sports · Events · catch-up · attribute chips | **Five Surfaces** | Which surfaces the data supports, and the settled answer that Sports and Events stay separate. |
| Sports row grammar | **Sport Rundown** | The 24 Q-tags. The discriminating-slot rule (sport glyph unfiltered, region once filtered), "General" as the catch-all name, progress bar vs countdown. Q&A round — **not** a layout mockup. |
| Database schema, storage, ingestion | **Where the Gigabytes Went** | Three independent audits merged. Index redundancy, the text foreign key, read-time JSON parsing, metadata duplication, stored credentials. |
| Open work, status, blockers | **MetaTV Worklog** | Living tracker. Every open item with a stable ID. |
| Overall interface | **MetaTV V3** · **Rows, Chips & Chrome** · **MetaTV Interface Overhaul** | The V3 pass, settled 2026-08-22 end to end. Do not re-litigate. |
| Watch Alerts rows | **Watch Alerts Row Grammar** · **Upcoming Heading Variants** | Row grammar settled against rendered evidence. |
| Lightbox | **MetaTV — Lightbox Redesign** | |
| Prior code audits | **MetaTV External Audit** · **MetaTV Audit V2** · **Triple Audit Bench** · **Remediation Plan** | Plus `docs/AUDIT_2026-06-19.md`, `docs/AUDIT_2026-08-16.md`, `docs/AUDIT_REBUTTAL_2026-08-27.md` in-repo. |

Get the URLs with `Artifact action:"list"` — they are stable per artifact, and
the titles above match exactly.

## The rule this encodes

Same rule the rest of the project runs on: *every finding that shipped with a
mechanical guard stayed at zero; every finding that relied on discipline
regressed.* "Remember to check the artifacts" is discipline. A file in the repo,
named in CLAUDE.md, that a grep for a feature name will hit — that is closer to
a guard.
