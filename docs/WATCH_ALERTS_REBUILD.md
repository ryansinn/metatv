# Watch Alerts — the 2026-08-26 rebuild

**Status: the design is built.** One slice remains (rows onto `chip_row`), listed
at the bottom. Everything else here is DONE and merged.

This file exists because the rebuild took a full day and spanned fifteen PRs. It
records what was decided, why, and what is left — so nobody re-derives it.

Approved design (rendered, the thing this was built against):
https://claude.ai/code/artifact/9783cee2-75d8-473e-992d-2c892d676975

---

## The section is the shared template

`CollapsibleSection` (`sidebar/base.py`) is the standard side-panel section, and
Watch Alerts had opted out of most of it. Dragging it back on is most of what
this rebuild was:

| template piece | before | now |
|---|---|---|
| section card (`SIDEBAR_SECTION_CARD`) | used | used |
| header band (`SECTION_HEADER_TINT`) | used, **but never painted for anyone** | fixed for every section |
| `make_status_label()` | hand-rolled the count into the title | shared |
| group headings | **three** different mechanisms | one `GroupHeading` widget |
| internal scroll | none | `content_scroll`, one per section |
| rows | own `alerts_rows.py` | **still diverged — the last slice** |

Fixes that landed in shared code reached History, Favorites, Queue and
Recommended automatically. That was the point.

---

## Decisions, and why

**Four groups, flat: EPG · Movies · Series · Stream Monitoring.** The
"Movies & Series" wrapper was dissolved: once every heading used one grammar it
read as a PEER of the two headings it contained — same weight, nested meaning.
EPG likewise stopped wrapping "Watch now"/"Upcoming"; it IS the group.

**One heading grammar.** `GroupHeading` is a WIDGET, not a styled item, because a
heading is two-toned — muted small-caps label beside a bright bold count — and a
`QListWidgetItem` has one font and one foreground. That is precisely why the
section had grown three mechanisms. Heading items are always `NoItemFlags`; the
click comes from the widget's signal, never from item flags. Flags doing double
duty as "is content" AND "is clickable" is what left one divider inert while its
identical twin collapsed.

**The count, not the title, carries state.** Colouring the whole title green and
appending " (N)" made the section read as a different section whenever something
arrived. The dot keeps the state; the count is a filled pill from
`make_status_label()`.

**One left slot, several markers.** Playing > hover > new. Green carries both
"playing" and "new" but as different SHAPES (triangle vs dot), so neither rests
on colour alone. Fixed width, so hover never reflows the row — the play button
used to live at the RIGHT edge and shoved the progress bar sideways.

**No play affordance on upcoming rows.** You cannot play a programme that has not
aired. A queue-it button was considered and dropped: the row already IS the
reminder.

**Quality by the title, no platform chip.** Quality is a claim about THIS copy —
the `quality` token block says so in as many words. Platform chips are
variable-width (`NF`, `D+`, `PRIME`, `Play+`), so leading with one gave every row
a different title start-x and the title column stopped being a column. Platform
also repeated identically on every sibling, so it distinguished nothing.

**Time is a chip; a programme row shows no bar.** Its airings carry the bars —
two bars in a parent/child pair measure the same thing twice. Bars are built at
their real fill, not zero-then-corrected.

**One scrollbar, at the section.** Views size to their rows (`fit_to_rows`) and
never scroll themselves. This is not a reversal of R13's no-nested-scrollbars:
that rule is about a ~35px band inside a subdivided panel, and there is exactly
one scrolling surface here.

**Budgeting is opt-in** (`sidebar_show_more_row`, Settings → Interface → Sidebar,
default OFF). Hiding rows is only worth doing when something can reveal them.
Forcing it on for Watch Alerts broke collapsing — the budget swallowed a group's
heading and replaced it with "See all N more →", which opened the manage dialog.

---

## Traps found the hard way

- **A plain `QWidget` ignores a stylesheet background without
  `WA_StyledBackground`.** `SECTION_HEADER_TINT` had been specified, resolved and
  never painted, in every section, for as long as it existed.
- **`apply_list_selection()` APPENDS to a stylesheet**, so anything applied after
  it silently replaces the selection rules and the view falls back to Qt's raw
  saturated highlight. Ledger F6 tracks auditing this app-wide.
- **`viewportSizeHint()` is the way to size a view to its contents.**
  `visualItemRect` is `(0,0,0,0)` before layout; `sizeHint().height()` returns
  **-1** when unset, which poisons a sum.
- **A signal bound to a `__new__`'d QObject's method registers but never
  delivers.** `receivers()` says 1 and nothing fires.
- **`COLOR_PLAYBACK_IN_PROGRESS` is ORANGE and means *resumable*.** Green
  ("currently playing") is `COLOR_OK`, per `DETAIL_PLAY_BTN_PLAYING`.
- Verifying a piece in isolation proves nothing about the assembled section, and
  a render harness that hand-builds widgets the production path never builds
  reports success for a screen the app cannot produce. Drive the real path.

---

## An empty group must not read as a missing feature

Reported as "epg section is totally missing from alert watch now", then "it
appears when making changes to epg watch items and then disappears
immediately". Nothing was broken: seven alerts were configured, the query was
correct, and the source's guide had simply run out of programmes to START — the
last one began at 10:38 that morning. `_populate_rows` answered an empty payload
by calling `_hide_epg_subsection()`, so the loading row revealed the group and
the empty result hid it again.

**The rule that came out of it:** a group disappears only when there is nothing
to hold a place for. No patterns and no EPG source are silent
(`EPG_EMPTY_SILENT`); a CONFIGURED watchlist with nothing airing keeps its
heading and names which nothing it is. Rendering "you have not set this up" and
"your setup is fine and quiet" identically — as absence — is what turns a
working feature into a bug report.

The notice is not a programme: `_reveal_epg_subsection(count=0)` and a
remembered `_epg_count` keep the heading chip empty, including across a
collapse, where re-deriving from `topLevelItemCount()` would resurrect a "1"
next to the words "Nothing airing".

### The trap underneath: coverage is measured by STARTS, not ends

`ProviderDB.epg_data_end` is the max `stop_time` of non-filler programmes. A
guide whose final entries run long reports coverage hours past the point where
anything new can begin — here it read 22:00 while the last start was 10:38. For
"On Now" that is harmless (something IS on). For a watchlist it is wrong: an
alert can only fire on a programme that starts. Hence
`EpgRepository.has_future_programmes()`, an EXISTS on `start_time > now`.

**Known, not fixed here:** `EpgManager.needs_refresh()`'s expiry floor keys off
that same `epg_data_end`, so a guide that has stopped producing new programmes
is not considered expired and no refresh is triggered — in the reported case,
for about six hours. Fixing it means changing convergence heuristics that have
been repaired twice for re-fetch loops (#285, #320), so it wants its own slice
with the loop guards thought through, not a drive-by edit on a UI branch.

---

## Left to do

**Rows onto `chip_row.build_chip_row()`.** Watch Alerts still has its own
`_AlertRow` / `_VodAlertRow` where History, Favorites, Queue and Recommended all
use the shared builder. That is why its rows do not middle-elide (long titles
CLIP where every other list elides with a tooltip) and why chips, the left slot
and spacing each had to be hand-added. Folding them in deletes most of
`alerts_rows.py` and makes the section structurally identical to its siblings.

Open questions when that lands: the EPG parent row needs a disclosure caret in
the same left slot as play/new (it currently uses the tree's native indicator),
and `chip_row` has no progress-bar tail yet.

**Also owed:** `alerts.py` is over the 1000-line standard; ledger F1 (migrate
Favorites/Queue off `style_group_heading`, then delete it); ledger F6 (selection
audit).
