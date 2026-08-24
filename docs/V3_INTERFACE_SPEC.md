# The V3 interface spec — decisions, and what is actually built

Two design passes, both conducted against rendered PyQt6 screens rather than
drawings, settled the interface on **2026-08-21/22**.

| | |
|---|---|
| Base pass — full analysis, R1–R14 revisions, Q1–Q21 decision register | <https://claude.ai/code/artifact/35c600d8-68b4-477c-93c8-340b447c00ab> |
| Finalised pass — the V3 renders | <https://claude.ai/code/artifact/53992418-55c5-48d7-b181-b4e0ebee4e81> |

> **Why this file exists, and why it is written this way.**
>
> For two days it did not exist. The wrap-up of the design session stated the
> spec had been captured in `docs/`; it had not. What survived was a condensed
> memory note, and that note recorded the sidebar as *shipped* on the strength
> of one of its six items — so the other five silently left the plan, and the
> next session built for a day against a list that no longer matched the spec.
> The header was missed the same way, and more completely.
>
> A settled design that is not in the repository cannot be checked against the
> tree, so it decays into whatever the last summary happened to keep. Hence the
> **status column on every row below**, and the rule that a ✅ must name the PR
> that earned it (CLAUDE.md: *shipped means proven, never planned*).

**Status keys:** ✅ built · ⚠️ partly built · ❌ not built · ⏸ deferred by owner.

---

## 0 · Migration checklist — the honest state

Verified against the tree, not against memory. Each ❌ is a slice.

**Re-verified 2026-08-24** after #445–#451. 15 of 26 items now ✅, 4 ⚠️ partly,
1 ⛔ rejected, 4 ❌, 2 ⏸. Every status below was checked by reading the tree —
a `✅` cites the PR that built it, and a `⚠️` says exactly what is missing
rather than rounding up. Item 8 is **rejected, not pending**: hiding the menu
bar behind ALT was tried and the owner reversed it (*"leave the menu visible,
because otherwise it's fucked on other platforms"*), so it must not reappear as
an unbuilt slice on a future sweep.

| # | Item | Where | Status |
|---|---|---|---|
| 1 | Row redesign | `channel_row_layout/_cells/_delegate` | ✅ #437 #439 |
| 2 | Radius scale | `tokens/scales.py` | ✅ #441 |
| 3 | Spacing grid | `tokens/scales.py` | ✅ #443 |
| 4 | Type scale, contrast, icons, surfaces | `theme_palettes`, `icons` | ✅ #325–#329 |
| 5 | Header row — brand · search · switcher · Split/Tools/Exclusions | `app_header.py` | ✅ #446 |
| 6 | Switcher in the header (Option A) | `app_header.py` | ✅ #446 — moved out of the bottom bar |
| 7 | Bottom bar freed | `main_window` | ✅ #446 — residents rehomed, not dropped |
| 8 | ~~Menu bar hidden behind ALT~~ | `main_window` | ⛔ **rejected by owner 2026-08-23** — *"leave the menu visible, because otherwise it's fucked on other platforms."* Not a slice. |
| 9 | Sidebar: no nested scrollbars | `sidebar/row_budget.py` | ✅ #447 |
| 10 | Sidebar: news boost | `sidebar/base.py` | ✅ #447 |
| 11 | Sidebar: collapsed headers carry news | `sidebar/base.py` | ✅ #447 |
| 12 | Sidebar: `+N more →` as an allocation consequence | `sidebar/row_budget.py` | ✅ #447 (crash fixed same PR: the marker had been stored in `UserRole`, where every section keeps its payload) |
| 13 | Sidebar: content-aware minimums | `sidebar/*` `MIN_ROWS` | ✅ #329 |
| 14 | Sidebar: `→` escalation, header-click expands | `sidebar/base.py` | ✅ #329 |
| 15 | Filter chips replacing the Includes column (Q3) | `filter_chips.py`, `filter_chip_bar.py`, `filter_chip_host.py` | ✅ #449 — `Layout ▸ Filters as chips` switches back |
| 16 | **Details: poster-led rebuild** (Q8/R8) | `details_pane` | ⚠️ **partly #450** — title freed of its badges, byline, poster art centred, Watched badge to top-right. The **two-column header** (poster left, title/meta right) is NOT built; the poster still spans the pane above the title block. |
| 17 | Details: Also-available grouped by region (Q19) | `details_version_groups.py` | ✅ #450 — 65 → 12 chips + tail; groups only above 12 versions |
| 18 | **Details: Similar titles header** — count + posters/list + ⤢ | `details_similar` | ⚠️ **partly** — the section is already at the bottom and Play is now hover-only (#451), but the header is still `Similar Titles (N)` with a collapse chevron: no right-aligned count, no toggle, no ⤢ |
| 19 | Details: sections collapsible with remembered state | `details_sections` | ⚠️ partly — Technical, Cast and Tags remember; Overview, Also-available and Similar do not |
| 20 | Language badge Filled/Outline/Off setting (R12/Q5) | `settings`, delegate | ❌ |
| 21 | Accent as its own axis — 6 hues × 2 modes (R14) | `theme_palettes` | ❌ |
| 22 | Inter bundled (O5) | `metatv/assets/fonts/` | ✅ #445 — Inter + a 7 KB 48-glyph Material Symbols subset, with `scripts/build_font_assets.py` |
| 23 | Option D — brand becomes the switcher, as a Settings option | `main_window` | ❌ |
| 24 | Series seasons/episode counts on the row meta line | DTO + repo | ❌ not plumbed |
| 25 | Configurable details layout (Q20) | — | ⏸ own slice |
| 26 | Similar-titles poster/list toggle | `ChannelVersion` has no poster URL | ⏸ blocked on DTO+hydration |

---

## 1 · Engine constraints (measured, not recalled)

Qt Widgets on Qt 6.11 / PyQt6 6.11.1.

**Honoured:** `border-radius`, gradients, `rgba()`, `letter-spacing`,
`font-size`/weight 100–900, per-side and dashed borders, `:hover`/`:focus`/
`:checked`/`:disabled`, `QPainter` in a delegate, `QGraphicsDropShadowEffect`.

**Dropped:** `box-shadow`, `opacity`, `transition`/`animation`, `transform`,
`text-shadow`, `backdrop-filter`/`filter`, `text-transform`, `line-height`,
`outline`, child-clipping to a parent's radius.

Consequences that have already cost time:

- **Elevation is layered surfaces + hairlines**, never shadows.
- Qt does **not** clip a child to its parent's `border-radius`. It looks like it
  does when the parent's sheet is unscoped, because the radius cascades. Scope
  with `#objectName` and a square corner bleeds through. Rounded posters must be
  pre-rounded into the pixmap.
- **A radius is honoured only while it is ≤ half the box's height.** One pixel
  over, Qt renders a **square** — it does not clamp. `border-radius: 999px` and
  `50%` both give a hard rectangle, so **a pill cannot be a token**; it is half
  of a specific control's height. (#441)
- `QPushButton` defaults to a **Fixed** vertical size policy — a cell will not
  fill its track without an explicit policy.
- `font-size` does not map 1:1 onto rendered height: 9px and 10px paint inside a
  1px band. Assert what Qt PAINTS.
- Three `opacity:` declarations shipped that Qt drops entirely — the widgets
  were never dimmed (Q13).
- **The channel list is not styled by CSS at all.** `ChannelRowDelegate` paints
  every row with `QPainter`, where none of the dropped features apply. *The
  surface that matters most is the least constrained.*

---

## 2 · Scales

| Scale | Decision | Status |
|---|---|---|
| Type (Q11) | 7 steps `11/12/13/15/17/20/26`, body 11→13px, weight carries the rest | ✅ #327 |
| Radius (Q10) | 4 steps — chip 4 · control 8 · card 12 · pill | ✅ #441 |
| Spacing (Q9) | 4pt grid; **horizontal axis only** — vertical sets height, which governs the radius rule | ✅ #443 |
| Surfaces | 7-step ramp, each a fill plus a hairline | ✅ #325 |
| Contrast (Q12) | `COLOR_FAINT/MUTED/DIM` failed AA in **36/36** combinations, worst 2.70:1, across 159 call sites | ✅ #325 |
| Density (Q6) | compact 34 · cozy 56 · comfy 68, one component three heights, 40×58 poster at comfy | ⚠️ heights follow content, not fixed steps |
| Palettes (Q15) | keep all three; Graphite is a genuinely distinct neutral | ✅ |
| Cinema surface (Q14) | lightbox + trail-map stay fixed-dark with their own `COLOR_LIGHTBOX_*` family; the new ramp stops at the app shell | ✅ |
| Accent (R14) | its own axis — 6 muted hues × dark/light, each ≥5.5:1 as text and ≥6:1 as a fill. `accent_color` already exists in config, just not formalised | ❌ |

Radius and the zoom transform are **palette-invariant** and live in
`gui/tokens/scales.py`, not the palette layer.

---

## 3 · Rows ✅

Three rules, in order of how much they matter.

1. **Nothing moves when a row is selected** (R9). The action slot is always
   *reserved*, painted only on hover/current. `row_layout()` takes **no state
   argument**, so a shifting column is unrepresentable, not merely avoided —
   which is also what makes it work by touch and keyboard, where hover does not
   exist.
2. **Kind is structural** (R2). Own mark in the leftmost gutter; own artwork
   shape — 2:3 poster, or a **square** tile for live, whose logo is a square
   asset. Row height does not vary by kind; the square tile centres inside the
   poster's height.
3. **Only render what exists** (Q18). Quality paints on the 6.6% of rows that
   have a value (live 26.2 / movie 3.3 / series 2.0) and is **not** a reserved
   column. *Reserve what is always true; render what is sometimes true.*

Settled details:

- **Quality hugs the title text**, not the title box, and is **not** in the
  right-hand rail. A right-aligned group is only stable if every member is
  always present; sharing a rail with quality made the language badge jump
  columns down a scrolling list (owner report, 2026-08-23).
- **The rail is the language family** — own language flush right, optional
  secondary / sub-dub markers extending leftward, so the tracked column is fixed.
- **No play button in rows** (R10): `▶` U+25B6 ink sits 1–2px low and differs
  per font. The overflow glyph is `⋯` **U+22EF**, never `…` U+2026.
- **Hover is not the only path** (R11) — the context menu carries everything.
- **No ratings in rows** (Q17/R3). Not objective; the top of the range is a wall
  of identical 10.0s. They belong in details with source and vote count.
- Meta line: `year · region · genres · collection · ×N`, `·` = U+00B7, genres
  joined ` / ` and capped at 3.
- Titles share a baseline whether or not a row has facts; selection is a **tint**
  plus a marker bar, so a selected row keeps its normal ramp and facet hues.
- **Reversal, 2026-08-23:** R2 had the kind spelled out as the meta line's first
  word — *"the glyph is for scanning, the word is for certainty"* — added back
  after the owner flagged losing media type. The owner reversed this on seeing
  it built: a filtered list read `Movie · … / Movie · …` down every row, so the
  word is gone and the mark carries it alone.

---

## 4 · Chrome ❌ — largely unbuilt

The V3 window is **one header row**, no bottom bar:

```
MetaTV │ ⌕ Search 491,624 titles…  │ [Search][EPG][Recommended][Discover][Recipe] │ [Split][Tools][Exclusions · 247]
```

- **Q2 / R7 — the switcher is Option A: divided segments in the HEADER**, accent
  fill on the active view, hairline dividers, a consistent cell box. Frees the
  bottom bar entirely. (Options B — top of sidebar, and C — bottom bar kept and
  made deliberate — were rendered and not chosen.)
  **What shipped (#328) is the Option A control in Option C's location.** The
  header itself was never built.
- **Option D** — brand recedes to a small label and the current view becomes the
  large clickable line beneath it. Ships as a *Settings interface option*, not
  the default. It always shows *where you are*, which a collapsed segmented
  control does not.
- **R5 — Split and Diagnostics return to the header.** Split is a lit-when-on
  toggle; Diagnostics lives behind a **Tools** button, because removing the menu
  bar would have orphaned it.
- **Q1 — the menu bar hides behind ALT**, reclaiming 22px. Qt has **no
  auto-reveal**: it needs an explicit ~10-line key handler that toggles
  visibility and takes menu focus. **Must be platform-guarded** — on macOS Qt
  hands the QMenuBar to the system menu bar, so hiding it would delete the app
  menu, and ALT means nothing there. An arm64 macOS build ships.
- **R6 — Settings appears once, at the foot of the sidebar.** It was in both
  places in an early mockup; that was a mistake. ✅ already correct in the tree.

---

## 5 · Sidebar ⚠️ — 2 of 6

**R1 — it stays a working surface.** Owner: *"The current sidebar UX is actually
good in that it allows a lot of fast interaction like quicklinks… like the
Alerts Matched +9 eps for President Curtis, that's useful. It's like 'oh a new
season dropped'."*

**A count is inventory; `+9 eps` is news.** Inventory tells you how much you
own; news tells you something changed, and only one of those is worth a glance.

**Q21 — the interaction model is unchanged**, three separate targets, all
surviving:

- header or chevron → expand/collapse, **never navigates**;
- `→` → opens that section's full view in the centre (`exploreClicked`);
- an item → acts on that item.

**R13 — the sidebar keeps everything; the bug is allocation.** Q7's "move heavy
content to the main pane" was **withdrawn**: *"Honestly: only vertical space.
That is not worth what it costs."* The measured saved layout:

| Section | Saved px | What fits |
|---|---|---|
| Watch Alerts | 173 | four sub-groups, each with its own scrollbar, ~35px apiece |
| Recommended | 113 | ~5 rows — *"OK"* |
| Watch Queue | 403 | *"looks great"* |
| Favorites | 26 | collapsed to its header |
| History | 91 | ~2 rows — *"doesn't have enough space"* |

Queue gets 4.4× History. Three mechanisms, no metaphor change:

1. **No nested scrollbars.** A section shows the rows that fit and ends with
   `+N more →`. Alerts stops being three tiny scrolling windows. *This alone
   recovers most of the jam.* ❌
2. **Content-aware minimums.** Each section declares the row count below which
   it stops being useful. ✅ #329 (`MIN_ROWS`)
3. **News boost.** A section holding something new gets a *bounded* extra
   allowance, so Alerts widens exactly when it has something to say. ❌

**Manual drag still wins and still persists** — this changes only the starting
allocation and the floor. Sections stay reorderable and individually hideable
(`sidebar_sections`, `sidebar_visible_sections`); the rail still hides.

`+N more` is **never a cap**: it is what appears when the allocated height runs
out. Drag taller and it renders more rows. History at 120px → 3 rows, 260px → 5,
440px → 11.

Collapsed sections carry news, not counts: `Watch Alerts — 1 new match`,
`Sources — 2 expiring`. Sub-groups inside a section get a small-caps header with
a `·`-separated count (`EPG · 5`), and an item with news states it at the right
(`1 new`, `+9 eps`) on a tinted row.

---

## 6 · Details pane ❌

**The action architecture is unchanged, because it was already right** (#259):
slim rail over the poster's left edge, Watched badge on the poster corner,
full-width primary row, sentiment trio at the right of the secondary row. This
was regressed once mid-design and rejected — *"bad design, we stepped away from
this."* **Do not flatten it.**

- **Q8 — poster-led.** Portrait poster at native 2:3 beside title and meta, then
  a real primary action row; Overview, Cast and Also-available as *content*, not
  empty disclosure rows. Today a 235×230 grey "No poster available" box heads a
  column that is mostly dead.
- **R8 — Similar titles restored.** Owner: *"It's missing similar titles, which I
  think is valuable. It's my hill to die on, I guess."* They move to the
  **bottom** with a header row: a count, a **posters / list** toggle, and `⤢` to
  open the cascading-column overlay. A handful, not all 18 — the overlay is where
  you browse; the pane says "there are more, here is the door." Posters keep
  their names.
- **Q19 — Also-available grouped by region**, that region's qualities collapsed
  onto the chip, with a `+N more regions` tail. Kraven The Hunter is **65
  versions across 20 regions**; Nickelodeon 94 across 32. Four lines instead of
  sixty-five. Grouping by *language* does not work: `detected_collection_language`
  is empty across the whole Nickelodeon group.
- Cast and Technical details collapsible, each remembering its state.

Known defect to fix **with** this slice, not before: the title is scrunched by
the badges sharing its row — a long title wraps to four lines. Same family as
the details-pane width trap.

---

## 7 · Filters ❌ (Q3)

The `Includes:` panel is a fixed ~250px column of ten ALL-CAPS facet rows with
roughly 360px of empty space beneath it, present whether or not you are
filtering. Active filters become **removable chips on one line**
(`Movies ×  4K ×  English ×  + Add filter`); `+ Add filter` opens the full panel
on demand. Returns ~250px of width to results.

Ships **behind** the existing panel so it can be switched back if the chips lose
the overview. *"This is the biggest layout change in the set, and the filter
panel is a core surface. It may deserve its own slice."*

---

## 8 · Notes that are not decisions

- **No `preferred_language`** exists in the code or anywhere in git history.
  `metadata_tmdb_language` is an open-text Settings field, but it sets the
  language TMDb metadata is *fetched* in, not which variant appears in results.
  The series monitor already records a language per tracked title, so a future
  global preference could seed from those.
- Similar-titles poster/list toggle is **blocked**: `ChannelVersion` carries no
  poster URL. Needs a DTO + repository + image-cache + async hydration first
  (`ChannelThumbnailHydrator` is the precedent).
- Q16 (icon style) — if the kind marks should be monochrome and quieter, that is
  a change to `icons.py`, **never a local override**; the icons rule makes that
  file the only source.
