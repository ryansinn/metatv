"""Recommended must not bounce you to the top when it refreshes (#290).

The scroll-reset fix (#275) was described as landing on "one shared chokepoint",
``BackgroundRefreshMixin``. It was one section short: ``RecommendedSection`` is
the mixin's documented exception (its ``None`` means "rate more content", a
valid empty state, not a load failure) and so inherited none of it. Its
``refresh()`` cleared the list with no capture and its result slot never
restored — so the section that owns the "≠ Show N versions separately" action
threw you back to row 1 every time you used it, on the row you had just found by
scrolling.

The helpers now live on ``ScrollPreservingMixin``, which every section inherits
through ``CollapsibleSection``, so the exception cannot miss out again.

Asserts RENDERED position, not just the scrollbar integer (CLAUDE.md: UI slices
assert appearance): the first row must actually be sitting above the viewport.
A restored scrollbar value with the rows still painted from the top would pass
an integer check and fail the user.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.config import Config
from metatv.gui.sidebar.recommended import RecommendedSection, _REC_LOAD_ERROR


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# These suites cover scroll PRESERVATION across a clear-and-repopulate — the
# "losing your place during bulk triage" bug, reported repeatedly. A section
# that opts into the row budget does not scroll at all (V3 R13: no nested
# scrollbars; overflow becomes "+N more"), so the sections here opt OUT of the
# budget to keep exercising that path. Budgeted behaviour is covered by
# tests/test_sidebar_allocation.py.
def _opt_out_of_row_budget(section):
    section.budgeted_list = lambda: None
    return section

def _rec(i: int) -> SimpleNamespace:
    """A stand-in ScoredCandidate carrying every field the row builder reads."""
    return SimpleNamespace(
        channel_id=f"ch-{i}",
        channel_name=f"Recommendation {i}",
        detected_title=f"Recommendation {i}",
        media_type="movie",
        reason="because you liked things",
        variant_count=1,
        metadata_rating=7.5,
        rec_shown_count=0,
        matching_genres=["Drama"],
        already_liked=False,
        detected_year="2024",
        detected_quality="HD",
        detected_prefix="EN",
    )


@pytest.fixture()
def section(qapp):
    """A REAL RecommendedSection with a list tall enough to scroll.

    ``db`` is never touched: every test drives the main-thread result slot
    directly and stubs the executor, so no background query runs.
    """
    sec = _opt_out_of_row_budget(RecommendedSection(Config(), db=None))
    sec._executor = SimpleNamespace(submit=lambda fn: None)
    sec.resize(240, 160)
    sec.show()
    QApplication.processEvents()
    sec._list.resize(240, 120)
    QApplication.processEvents()
    yield sec
    sec.hide()


def _fill(section, n: int = 40) -> None:
    section._on_rec_data_ready(([_rec(i) for i in range(n)], {}))
    QApplication.processEvents()


def _scroll_to_middle(section) -> int:
    bar = section._list.verticalScrollBar()
    target = bar.maximum() // 2
    assert target > 0, "fixture did not produce a scrollable list"
    bar.setValue(target)
    QApplication.processEvents()
    return bar.value()


def test_a_refresh_keeps_your_place(section):
    """The defect, end to end: scroll down, refresh, still be there."""
    _fill(section)
    where = _scroll_to_middle(section)

    section.refresh()               # clears the list (executor stubbed out)
    _fill(section)                  # the result arriving back on the main thread

    assert section._list.verticalScrollBar().value() == where, (
        f"Recommended jumped to {section._list.verticalScrollBar().value()} "
        f"after a refresh — the user was reading row ~{where // 30}"
    )


def test_the_restored_rows_are_actually_painted_scrolled(section):
    """Rendered appearance, not just the integer.

    The first row must be laid out ABOVE the viewport — that is what "you are
    still where you were" looks like on screen.
    """
    _fill(section)
    _scroll_to_middle(section)

    section.refresh()
    _fill(section)

    first_row = section._list.visualItemRect(section._list.item(0))
    assert first_row.bottom() < 0, (
        f"row 0 is painted at y={first_row.top()} — the list is rendering from "
        f"the top even though the scrollbar was restored"
    )


def test_show_versions_separately_keeps_your_place(section):
    """The real action that triggers this refresh, exercised through its handler.

    Right-clicking a grouped row deep in the list and choosing "Show N versions
    separately" calls ``refresh()``. Losing the position there is worst of all:
    the row you acted on is the one you can no longer find.
    """
    _fill(section)
    where = _scroll_to_middle(section)

    section._on_show_separately("ch-18")
    _fill(section)

    assert section._list.verticalScrollBar().value() == where
    assert "ch-18" in section.config.rec_dedupe_overrides, (
        "the action itself stopped working"
    )


def test_a_shorter_result_is_clamped_not_out_of_range(section):
    """A refresh can return fewer rows; the old offset then exceeds the max."""
    _fill(section, 40)
    _scroll_to_middle(section)

    section.refresh()
    _fill(section, 3)

    bar = section._list.verticalScrollBar()
    assert bar.value() <= bar.maximum()


@pytest.mark.parametrize(
    "payload, expect_text",
    [
        (None, "Rate movies"),
        (([], {}), "No recommendations yet"),
        (_REC_LOAD_ERROR, "Couldn't load"),
    ],
)
def test_placeholder_renders_are_never_scrolled_out_of_view(
    section, payload, expect_text
):
    """Each one-line placeholder must be visible, not scrolled past.

    Restoring a 40-row offset onto a 1-row list would hide the only thing the
    section has to say. Two halves: the offset is discarded rather than
    re-applied, and the row lands inside the viewport once the list is on
    screen. (The empty-state branches auto-collapse the section, so the list is
    shown explicitly here — the assertion is about where the row is PAINTED
    when visible, not about the collapse.)
    """
    _fill(section)
    _scroll_to_middle(section)

    section.refresh()
    section._on_rec_data_ready(payload)
    QApplication.processEvents()

    assert "_pending_scroll" not in section.__dict__, (
        "a 40-row offset survived into a one-row render — it would scroll the "
        "message out of view"
    )
    assert expect_text in section._list.item(0).text()

    section._list.show()
    QApplication.processEvents()
    rect = section._list.visualItemRect(section._list.item(0))
    assert rect.top() >= 0 and rect.height() > 0, (
        f"the placeholder row is painted at y={rect.top()} — off the top of "
        f"the viewport, so the section reads as blank"
    )
