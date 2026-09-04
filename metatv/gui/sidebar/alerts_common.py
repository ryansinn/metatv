"""Values every Watch Alerts module shares.

Split out so the three group modules (:mod:`alerts_epg`, :mod:`alerts_vod`,
:mod:`alerts_monitor`) and the section shell can each import them without
importing one another — the constants, the ``_Airing`` record the EPG loader
emits, and its tolerant accessors.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple
from PyQt6.QtCore import Qt
from metatv.gui.sidebar.alerts_rows import _AlertRow, _CHILD_INDENT  # noqa: F401

# Re-exported deliberately: two alerts modules import _CHILD_INDENT from here
# rather than from alerts_rows, because this module is the shared vocabulary for
# the alerts family. Declared so the linter keeps it and a reader knows why.
__all__ = ["_CHILD_INDENT"]


# Item-data roles for the Movies & Series list (_vod_list).  UserRole stays the
# rule_created id for keyword-rule rows (existing click/menu code reads it); the
# extra roles tag the item kind and, for series rows, the series channel id.
_ROLE_KIND = Qt.ItemDataRole.UserRole + 5        # "rule" | "heading" | "series"
#: Height assumed for a row that never had an explicit size hint set —
#: a plain text item rather than one carrying a widget.
_ROW_FALLBACK_H = 22


_ROLE_SERIES_ID = Qt.ItemDataRole.UserRole + 6   # series_channel_id (series rows)
# Stable key for a collapsible EPG group, so the user's expand/collapse choice
# survives the tree being rebuilt on every refresh. The QTreeWidgetItem does not:
# it is destroyed and recreated, taking its expanded state with it.
_ROLE_GROUP_KEY = Qt.ItemDataRole.UserRole + 7   # programme title (EPG group rows)


def _quality(airing) -> str:
    """The airing's quality token, or "" — sibling of :func:`_when`."""
    return airing[6] if len(airing) > 6 else ""


def _region(airing) -> str:
    """The airing's region/language token, or "" — sibling of :func:`_quality`."""
    return airing[7] if len(airing) > 7 else ""


def _prog_start(airing) -> "datetime | None":
    """The airing's TRUE programme start (unpadded, regardless of live/upcoming),
    or ``None`` — REC-3. Sibling of :func:`_prog_stop`.

    Unlike ``started_at`` (only populated for a LIVE airing, for the progress
    bar), this is always the guide's real start — what
    ``schedule_recording_from_programme`` needs to schedule the row's OWN
    window rather than "now".
    """
    return airing[8] if len(airing) > 8 else None


def _prog_stop(airing) -> "datetime | None":
    """The airing's TRUE programme stop (unpadded), or ``None`` — sibling of
    :func:`_prog_start`."""
    return airing[9] if len(airing) > 9 else None


def _started_at(airing) -> "datetime | None":
    """The airing's start, or ``None`` — sibling of :func:`_when`.

    Same tolerance for a hand-built short tuple from a test seam.
    """
    return airing[5] if len(airing) > 5 else None


def _when(airing) -> "datetime | None":
    """The airing's timestamp, or ``None`` for a record that predates the field.

    Not defensive programming for its own sake: ``_load_rows`` always produces
    an :class:`_Airing`, but this dict is a documented seam that tests build by
    hand, and a four-element tuple from one of those should render a row that
    simply does not self-refresh rather than raise.
    """
    return airing[4] if len(airing) > 4 else None


class _Airing(NamedTuple):
    """One airing of one programme on one channel, as ``_load_rows`` hands it on.

    A NamedTuple rather than a bare tuple because this grew a fifth field and
    the plain-tuple version broke five tests that unpacked it — positional
    tuples do not survive gaining a member. Index access still works, so the
    existing ``a[1]`` / ``a[2]`` call sites are untouched, and ``when``
    defaults so a four-field construction stays legal.

    Attributes:
        sort_key: Minutes-left for a live airing, epoch seconds for an upcoming
            one — whichever orders that list.
        time_text: The rendered time as of load. Correct only for that instant;
            the row recomputes it on the tick (see ``_AlertRow.refresh_time``).
        channel: Display name of the channel.
        channel_db_id: The channel's DB id, for play/select.
        when: ``stop_time`` for a live airing, ``start_time`` for an upcoming
            one, UTC-naive. This is what makes the row refreshable and what
            ``_schedule_boundary`` aims its timer at.
        started_at: ``start_time`` for a LIVE airing, so the row can show how
            far through the programme is. ``when`` alone gives the end but not
            the duration, and 30 minutes left means something different on a
            half-hour show than on a three-hour one. ``None`` on upcoming rows,
            which have not started.
        prog_start: The programme's real start, UTC-naive, unpadded — set for
            EVERY airing (live or upcoming), unlike ``started_at``. What
            "record_programme" (REC-3) schedules from, since a recording of a
            not-yet-started programme needs its own window rather than "now".
        prog_stop: The programme's real stop, UTC-naive, unpadded — sibling of
            ``prog_start``. ``when`` cannot stand in for this: on an upcoming
            airing ``when`` IS ``start_time``, not the stop.
    """

    sort_key: float
    time_text: str
    channel: str
    channel_db_id: str
    when: "datetime | None" = None
    started_at: "datetime | None" = None
    quality: str = ""
    region: str = ""
    prog_start: "datetime | None" = None
    prog_stop: "datetime | None" = None

# Row budget (px) for _apply_expansion()'s "expand every group only if the fully
# expanded list still fits a compact height" decision.  It is NOT a widget maximum:
# the three sub-lists share the section's height via equal layout stretch (see
# create_content), so the EPG tree is bounded by its stretch share of the splitter
# pane, not by a hard cap.  A hard cap was deliberately dropped — capping the tree to
# its content left the section's surplus space pooling as a blank gap at the bottom.
_ALERTS_TREE_AUTOEXPAND_BUDGET = 320


def _vod_count_label(unviewed: int, count: int) -> str:
    """Right-aligned count text for a watch-for rule row.

    The count is a CHIP, so it carries no leading "·". That dot was a separator
    from when the count was loose text sharing a line with the title — inside a
    chip it reads as part of the number.

        - unviewed > 0:             "+{unviewed}"  (a filled news pill)
        - unviewed == 0, count > 0: "{count}"
        - count == 0:               ""

    Args:
        unviewed: Unviewed match count for this rule.
        count: Total match count for this rule.

    Returns:
        The count label text (possibly empty).
    """
    if unviewed > 0:
        # "+5", not "5 of 20": the chip is narrow, and how many are NEW is the
        # fact worth the space. The total is in the row's tooltip.
        return f"+{unviewed}"
    if count > 0:
        return str(count)
    return ""
