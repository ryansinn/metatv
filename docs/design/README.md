# Design records

Self-contained HTML. Open either in a browser — every render is inlined as a
data URI, so they work offline and forever, with no dependency on claude.ai.

| File | What it is |
|---|---|
| `v3-interface-overhaul.html` | The **base pass**. Full analysis of the app as it stood, the measured Qt capability table, R1–R14 revisions written against owner review, and the **Q1–Q21 decision register** with *Today / Proposed / Watch out* for each. Hours of Q&A. |
| `v3-metatv-redrawn.html` | The **finalised pass** — "MetaTV, redrawn". The V3 renders, every one produced by PyQt6 against a copy of the real 491,624-title library. |

The distilled, checkable version — every decision with a **built / not built**
status verified against the tree — is [`../V3_INTERFACE_SPEC.md`](../V3_INTERFACE_SPEC.md).
Read that first; come here for the pictures and the full reasoning.

## Why these are vendored rather than linked

They were linked, once. The design session's wrap-up reported the spec as
captured in `docs/`; it was not, and what survived was a condensed memory note
that recorded the sidebar as *shipped* on the strength of one of its six items.
A day of work then proceeded against a list that no longer matched the spec, and
the header — the most visible single element of the redesign — was missed
entirely because nothing in the repository mentioned it.

An artifact URL is not a record the tree can be checked against.

## The font assets — recovered

These were built in a session scratchpad and lost with it. They have since been
regenerated **into the repository** (#445), which is where anything the build
consumes belongs:

| Asset | Where | Licence |
|---|---|---|
| `Inter-Regular.ttf` / `Inter-SemiBold.ttf` | `metatv/assets/fonts/` | OFL-1.1 |
| `MetaTVIcons.ttf` — Material Symbols Outlined, 48-glyph subset, **7 KB** | `metatv/assets/fonts/` | Apache-2.0 |

`scripts/build_font_assets.py` regenerates all three from upstream, and
`metatv/gui/fonts.py` loads them via `QFontDatabase.addApplicationFont`. The
codepoint map ships beside the font so `icon_char()` resolves a name to a glyph
without guessing.

IBM Plex Sans was the other candidate and was not chosen; it is not vendored.
