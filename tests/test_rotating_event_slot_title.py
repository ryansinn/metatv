"""A rotated event slot must not keep showing the previous fixture's title.

The owner, looking at the Sports rundown: *"why is sports showing US Hockey as
On Now that says it aired DAYS ago?"* — and then, decisively, *"the title of the
mpv stream doesn't match the title shown in the app"*.

Measured on their library, one row explains both:

    name             (FLSP 154) | hockey: Drayton Valley Thunder vs Grande
                     Prairie Storm (Home) (2026-09-01 20:00:05)
    event_start_time 2026-09-01 18:00     -> genuinely inside the live window
    sport_type       hockey               -> correct for tonight's fixture
    detected_title   (FLSP 154) | flovolleyball: … (2026-08-28 12:00:05)   STALE

The lane was right and the clock was right. **Render reads detected_title**, so
the row wore last week's volleyball fixture over tonight's hockey game — which
is exactly why the app and mpv disagreed about what was playing.

1,077 of 2,940 dated event rows (36.6%) were in that state. The provider rotates
these slots daily, so this is the normal case, not an edge one.

#629 already nulls the derived fields on rename and lets ingestion refill them.
It is not enough on its own and this file is about why: it has **no backfill**,
and a row that went stale before it shipped never changes name again, so nothing
ever nulls it.
"""

from __future__ import annotations

from metatv.core.channel_name_utils import parse_channel_name
from metatv.core.migrations import detected_title_reparse as reparse

#: The owner's actual row, before and after the slot rotated.
PREVIOUS = ("(FLSP 154) | flovolleyball: 2026 Missouri_St. Louis vs Cedarville "
            "_ Women`s (UMSL vs Cedarville) (2026-08-28 12:00:05)")
CURRENT = ("(FLSP 154) | hockey:  Drayton Valley Thunder vs Grande Prairie "
           "Storm (Home) (2026-09-01 20:00:05)")


def test_reparsing_the_current_name_replaces_the_previous_fixture():
    """The repair has to actually produce tonight's fixture, not just differ."""
    derived = parse_channel_name(CURRENT).bare_name or ""

    assert derived != PREVIOUS, "the stale title survived a re-parse"
    assert "Drayton Valley" in derived, (
        f"the re-parse did not recover tonight's fixture: {derived!r}")
    assert "flovolleyball" not in derived
    assert "2026-08-28" not in derived, "last week's date is still in the title"


#: The version that carries the rotated-slot repair. A FLOOR, not an equality:
#: later bumps are fine and must not fail this, but dropping back below it
#: silently strands every already-stale row.
REPAIR_VERSION = 13


def test_the_reparse_migration_is_owed_to_anyone_stuck_on_the_old_version():
    """The bump IS the fix — without it the 1,077 rows are never revisited.

    The version is pinned to a floor deliberately. My first draft asserted
    ``needs_run`` against ``CURRENT_VERSION - 1``, which passes at ANY version —
    including the one that shipped the bug — so it proved only that the version
    gate compares two numbers. Mutation-checked: reverting 13 to 12 left it
    green. The thing worth guarding is that the repair version is actually
    reached.
    """
    assert reparse.CURRENT_VERSION >= REPAIR_VERSION, (
        f"detected_reparse_version {reparse.CURRENT_VERSION} is below "
        f"{REPAIR_VERSION}: every row already carrying a previous fixture's "
        f"title stays that way, because nothing else ever revisits it")

    # And the gate itself still works in both directions.
    class _Cfg:
        detected_reparse_version = REPAIR_VERSION - 1

    task = reparse.DetectedTitleReparseTask(None)
    assert task.needs_run(_Cfg()), "a config behind the repair is not repaired"

    _Cfg.detected_reparse_version = reparse.CURRENT_VERSION
    assert not task.needs_run(_Cfg()), "the migration would re-run every launch"


def test_the_rotated_slot_is_not_treated_as_a_different_title_by_accident():
    """Non-degeneracy: the two names really are different fixtures.

    If the parser collapsed both to the same string this file would pass while
    proving nothing, so the premise is asserted rather than assumed.
    """
    before = parse_channel_name(PREVIOUS).bare_name or ""
    after = parse_channel_name(CURRENT).bare_name or ""
    assert before != after, "the two fixtures parse identically — no bug to fix"
    assert "Missouri" in before and "Drayton" in after
