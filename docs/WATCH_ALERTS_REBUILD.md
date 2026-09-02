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

**Nothing is budgeted any more** (removed 2026-09-02). Every row is shown and
the section scrolls. Rows were only ever hidden when something could reveal
them, and the thing that was supposed to — *"wheeling the list reveals more
(see eventFilter)"* — did not exist; the tail row was the only way, so the
mode's stated audience, people who cannot use a wheel, was the one group it
failed. Forcing it on for Watch Alerts had already broken collapsing, by
swallowing a group's heading and replacing it with "See all N more →".

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

## Rows onto the shared builder (done)

Watch Alerts was the last section hand-assembling a `QHBoxLayout` while History,
Favorites, Queue and Recommended all used `chip_row.build_chip_row()`. Three
symptoms, one cause: titles CLIPPED where every other list middle-elides; chips
were rebuilt from copied stylesheet strings applied with `setStyleSheet`, which
renders once and so went stale on a theme switch; and spacing had to be
re-derived by hand every time the design moved.

Both rows are now shells over the builder. What stayed behind is what a shared
builder cannot own: the left slot's *painting* (which marker applies right now),
the clock tick, and `_AlertRow`'s mouse handling.

**Four slots were added to `build_chip_row` rather than trimmed off a copy** —
each a real grammar element, now available to every section:

| slot | what it is |
|---|---|
| `leading_slot` | a caller-owned fixed-width column at the absolute left. Reserving the column is the point: a marker appearing on hover cannot shove the row |
| `title_chips` | chips that travel WITH the title (quality, episode code) as against `chips`, which are facts about the row's place in the list |
| `title_suffix` | the dim disambiguator. Takes `SIDEBAR_ROW_TAIL`, the existing "terse and subordinate" role — not a second definition of the same idea |
| `tail_widget` | a right-cluster fact that cannot be a string. The progress bar |

Plus `indent`, and `CHIP_NEWS` — the filled `+N` pill, moved out of
`alerts_rows` so one place owns it.

**Two traps this hit, both about sizing.** A row built by the shared builder
reports the builder's tighter height, so `item.setSizeHint(row.sizeHint())` gave
20px rows where the section wants 29 — and it reports its NATURAL width (462px
for a long rule name against a 300px sidebar), which widens the list instead of
eliding inside it. `_RowShell.sizeHint()` fixes both: full row height, minimum
width. The width half is why Watch Alerts titles clipped for as long as the
section built its own rows.

## The file split (done)

`alerts.py` had reached ~1800 lines against the 1000-line standard. Split along
the four groups the design already names, not by line count:

| module | lines | what |
|---|---|---|
| `alerts.py` | ~530 | the section shell — header, content, empty state, budget |
| `alerts_epg.py` | ~650 | `EpgGroupMixin` — the query, the render, the clock |
| `alerts_vod.py` | ~540 | `MoviesSeriesMixin` — keyword rules and monitored series |
| `alerts_monitor.py` | ~90 | `StreamMonitoringMixin` — retried streams |
| `alerts_common.py` | ~150 | constants, `_Airing`, its tolerant accessors |

The mixins hold no state; they reach the widgets `create_content` builds through
`self`. `alerts.py` re-exports the shared names, so the split is invisible from
outside — every existing `from ...alerts import _ROLE_KIND` still works.

Found while splitting: `_toggle_series_group`, `_toggle_keyword_group` and
`_add_group_heading` were each defined **twice**, a verbatim 42-line block
(identical MD5). The second copy silently won; the first was dead. Removed.

## The section is a noticeboard, not the watchlist

`alerts_show_idle_items` (default **off**) filters Movies and Series to entries
that have something new. The standing list of what you are waiting for is a
different question, answered in Manage Watch Alerts and — for EPG keywords —
the EPG view's Watch tab. EPG and Stream Monitoring are unfiltered by
construction: both already list only what is happening now.

Three things this had to get right:

* **Counted before filtered.** The header badge and `_firing_count` /
  `_series_new_count` are computed from the FULL sets; only the display is
  filtered. A filter that changed the counts would make the section disagree
  with itself.
* **A heading counts its rows**, so "SERIES 2" with seven monitored is honest
  about what it lists. What is missing goes in the tooltip via `_hidden_note()`,
  where there is room to say what to do about it.
* **Configured-but-quiet is not empty.** `_show_idle_only_notice()` keeps the
  place with "Nothing new from N alerts" — the same lesson as the EPG group,
  and for the same reason: an absent feature and a quiet one must not render
  identically.

**One setting, two switches.** Settings → Interface → Watch Alerts and Manage
Watch Alerts both read and write `config.alerts_show_idle_items`, so they cannot
disagree. The manage dialog writes on toggle (it has no OK button) and emits
`changed`, which the host already routes to `_refresh_vod_alerts_section`; the
settings dialog goes through `settings_applied`, which now carries that same
hook.

## A collapsed group wears its new count

`GroupHeading.set_news(n)` draws the filled `+N` pill — `chip_row`'s
`CHIP_NEWS`, the one definition of that pill, so it matches the section header
and re-renders on a palette switch. It appears **only while the group is
collapsed**: expanded, every firing row already carries its own green marker and
a pill on the heading would say it twice; collapsed, the rows are gone and the
heading is the only thing left that can tell you something arrived.

## The programme row: two leading columns

A programme on several sources has a **source-stack marker** hanging in the
left margin at exactly `_CHILD_INDENT` wide, then its **play slot**. That width
is load-bearing: it pushes the parent's play slot into the same column as its
children's, so the play affordances form one continuous line down the group and
the parent's title shares its left edge with its sources'. One constant, in
`alerts_rows`, because two numbers that must be equal are one number.

Three owner reports, one cause — expansion was wired to `play_clicked`, which
fires only on the 18px slot AND only when the row counts as playable, so an
expandable row had to claim it was playable to open at all:

* clicking the title did nothing; only the marker strip responded
* the marker drew a play triangle on hover, on a control that expands
* "carot and play buttons look way too similar" — true at 14px

Now `expand_clicked` fires from anywhere that is not the play button, and the
marker is `sources_closed`/`sources_open` (two stacked boxes, outline → filled),
NOT the app-wide `expand`/`collapse` chevrons, which keep their own keys for
every other disclosure in the app.

Play on the parent plays the **first live airing as the group is ordered**. That
is a placeholder, and it is on the roadmap as "preferred playback source for a
watched show" — owner: "user doesn't typically care about row".

## Row density

`ROW_PAD_Y` 5 → 2 and the group heading's lead-in 10 → 5. That is a halving of
the padding, not of the row: 12px around a 17px line box became 6px, so rows are
23px rather than 29px. Owner: "the space between each item is a wasted row ...
spacing between rows should be cut in half".

The descender is safe at any padding here — the clipping that produced the 5px
value came from sizing a row to its tallest CHILD, and the fix was measuring the
font's full line box in `_RowShell._mount`, which the padding is merely added to.

## Left to do

Ledger F1 (migrate Favorites/Queue off `style_group_heading`, then delete it);
ledger F6 (selection audit); ledger F8 (a dead guide is not detected as
expired).
