"""Values every Watch Alerts module shares.

Split out so the three group modules (:mod:`alerts_epg`, :mod:`alerts_vod`,
:mod:`alerts_monitor`) and the section shell can each import them without
importing one another — the constants, the ``_Airing`` record the EPG loader
emits, and its tolerant accessors.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel
from datetime import datetime
from typing import NamedTuple
from PyQt6.QtCore import Qt
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.alerts_rows import _AlertRow


# Item-data roles for the Movies & Series list (_vod_list).  UserRole stays the
# rule_created id for keyword-rule rows (existing click/menu code reads it); the
# extra roles tag the item kind and, for series rows, the series channel id.
_ROLE_KIND = Qt.ItemDataRole.UserRole + 5        # "rule" | "heading" | "series"
#: Height assumed for a row that never had an explicit size hint set —
#: a plain text item rather than one carrying a widget.
_ROW_FALLBACK_H = 22

#: How far a child airing insets from its programme row. The row does
#: this itself now — the tree's own indentation also moved TOP-LEVEL
#: rows, which is what gave the section two left edges.
_CHILD_INDENT = 14

_ROLE_SERIES_ID = Qt.ItemDataRole.UserRole + 6   # series_channel_id (series rows)


def _quality(airing) -> str:
    """The airing's quality token, or "" — sibling of :func:`_when`."""
    return airing[6] if len(airing) > 6 else ""


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
    """

    sort_key: float
    time_text: str
    channel: str
    channel_db_id: str
    when: "datetime | None" = None
    started_at: "datetime | None" = None
    quality: str = ""

# Row budget (px) for _apply_expansion()'s "expand every group only if the fully
# expanded list still fits a compact height" decision.  It is NOT a widget maximum:
# the three sub-lists share the section's height via equal layout stretch (see
# create_content), so the EPG tree is bounded by its stretch share of the splitter
# pane, not by a hard cap.  A hard cap was deliberately dropped — capping the tree to
# its content left the section's surplus space pooling as a blank gap at the bottom.
_ALERTS_TREE_AUTOEXPAND_BUDGET = 320


def _alerts_title_html(title: str, count: int) -> str:
    """Rich-text for the Alerts header: a recolorable status dot + title + count.

The DOT carries the state; the title does not. Colouring the whole title
    green and appending " (N)" made the header read as a different section
    when something was new, and the count then had no chip of its own — the
    approved design has a plain white title beside a filled green pill, which
    is what ``make_status_label`` already renders for every other section.

        - Quiet (count == 0): grey dot, plain title.
        - Active (count > 0): green dot, plain title. The count lives in the
          header's status label.

    Args:
        title: The section title (always "Watch Alerts").
        count: Number of unviewed watch-for matches across all rules.

    Returns:
        An HTML string for :meth:`QLabel.setText` (rich-text format).
    """
    dot_color = _theme.COLOR_OK if count > 0 else _theme.COLOR_MUTED
    return (
        f'<span style="color:{dot_color}">{_icons.status_dot_icon}</span> '
        f'<b><span style="color:{_theme.COLOR_TEXT_HI}">{title}</span></b>'
    )


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
