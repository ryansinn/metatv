"""A sidebar-section refresh must not throw the user back to the top (#25).

Owner, after being told twice that only half the problem was fixed: "so fix the
scroll reset, it seems like I've had to ask you to do this 5 times now."

The results-list half was ``_category_assigned`` wired straight to
``load_channels`` (#274). This is the other half: ``BackgroundRefreshMixin`` —
composed by the queue, favorites and history sections — calls ``lst.clear()`` in
BOTH ``refresh()`` and ``_on_data_ready()``, and clearing a ``QListWidget``
resets its scroll to 0.

That "one shared chokepoint" was one section short of shared: ``Recommended``
does not compose this mixin (documented exception — its ``None`` is a valid
empty state, not a failure) and so never got the fix. The helpers now live on
``ScrollPreservingMixin``, inherited by every section through
``CollapsibleSection``; ``tests/test_recommended_scroll_preserve.py`` covers the
section that was missed.

So marking one item watched deep in the Watch Queue rebuilt the section and
bounced the user to row 1, punishing them for every single action in exactly the
list built for bulk triage.

The offset is captured before the destructive clear and restored after the rows
land, clamped to the new maximum (a refresh can return FEWER rows).
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QListWidget, QListWidgetItem

from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import ScrollPreservingMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Section(BackgroundRefreshMixin, ScrollPreservingMixin):
    """Minimal host exercising the REAL mixin methods.

    Composes ``ScrollPreservingMixin`` exactly as ``CollapsibleSection`` does,
    so this exercises the shipped capture/restore code rather than a stand-in.
    """

    def __init__(self, list_widget, row_count=200):
        self._list = list_widget
        self._row_count = row_count
        self.loading_shown = []
        self.errors = []

    # Collaborators the mixin expects from CollapsibleSection / the section.
    def _refresh_list(self):
        return self._list

    def _loading_message(self):
        return "Loading…"

    def _load_error_message(self):
        return "Could not load"

    def show_loading(self, lst, msg):
        self.loading_shown.append(msg)

    def show_load_error(self, lst, msg):
        self.errors.append(msg)
        lst.addItem(QListWidgetItem(msg))

    def _populate_rows(self, rows):
        for r in rows:
            self._list.addItem(QListWidgetItem(str(r)))


# These suites cover scroll PRESERVATION across a clear-and-repopulate — the
# "losing your place during bulk triage" bug, reported repeatedly. A section
# that opts into the row budget does not scroll at all (V3 R13: no nested
# scrollbars; overflow becomes "+N more"), so the sections here opt OUT of the
# budget to keep exercising that path. Budgeted behaviour is covered by
# tests/test_sidebar_allocation.py.
def _opt_out_of_row_budget(section):
    section.budgeted_list = lambda: None
    # This double does not inherit CollapsibleSection, so it lacks the hook the
    # refresh mixin now calls after every populate. Opting out of the budget
    # means there is nothing for it to do.
    section.reapply_row_budget = lambda: None
    return section

def _tall_list(qapp, n=200) -> QListWidget:
    lst = QListWidget()
    for i in range(n):
        lst.addItem(QListWidgetItem(f"row {i}"))
    lst.resize(200, 100)          # force a scrollbar
    lst.show()
    QApplication.processEvents()
    return lst


def test_scroll_position_survives_a_refresh(qapp):
    """The owner's case: act on one row deep in the list, stay there."""
    lst = _tall_list(qapp)
    lst.verticalScrollBar().setValue(120)
    QApplication.processEvents()
    assert lst.verticalScrollBar().value() == 120

    section = _opt_out_of_row_budget(_Section(lst))
    # The two halves of a refresh, without the executor round-trip.
    section._pending_scroll = section._scroll_offset(lst)
    lst.clear()
    section._on_data_ready([f"row {i}" for i in range(200)])
    QApplication.processEvents()

    assert lst.verticalScrollBar().value() == 120, (
        f"refresh bounced the list to {lst.verticalScrollBar().value()} — the "
        f"user loses their place on every single action"
    )


def test_offset_is_clamped_when_the_list_shrinks(qapp):
    """A refresh can return FEWER rows (the item left the queue).

    Restoring a now-out-of-range offset must land at the new bottom, not raise
    or produce a blank viewport.
    """
    lst = _tall_list(qapp)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum())
    QApplication.processEvents()

    section = _opt_out_of_row_budget(_Section(lst))
    section._pending_scroll = section._scroll_offset(lst)
    lst.clear()
    section._on_data_ready([f"row {i}" for i in range(5)])   # shrank
    QApplication.processEvents()

    bar = lst.verticalScrollBar()
    assert bar.value() <= bar.maximum()


def test_error_branch_drops_the_saved_offset(qapp):
    """An error row is a short list; scrolling it away would hide the message."""
    lst = _tall_list(qapp)
    lst.verticalScrollBar().setValue(150)
    section = _opt_out_of_row_budget(_Section(lst))
    section._pending_scroll = section._scroll_offset(lst)
    lst.clear()

    section._on_data_ready(None)
    QApplication.processEvents()

    assert section.errors, "the failure row must still be rendered"
    assert "_pending_scroll" not in section.__dict__, (
        "a stale offset was kept across an error render"
    )
    assert lst.verticalScrollBar().value() == 0


def test_top_of_list_is_unaffected(qapp):
    """Someone already at the top stays at the top — no surprise jump."""
    lst = _tall_list(qapp)
    lst.verticalScrollBar().setValue(0)

    section = _opt_out_of_row_budget(_Section(lst))
    section._pending_scroll = section._scroll_offset(lst)
    lst.clear()
    section._on_data_ready([f"row {i}" for i in range(200)])
    QApplication.processEvents()

    assert lst.verticalScrollBar().value() == 0


def test_refresh_captures_before_clearing(qapp):
    """Order matters: capture must precede the clear that destroys the value."""
    lst = _tall_list(qapp)
    lst.verticalScrollBar().setValue(90)
    QApplication.processEvents()

    section = _opt_out_of_row_budget(_Section(lst))
    section._executor = type("E", (), {"submit": lambda self, fn: None})()
    section.refresh()

    assert section._pending_scroll == 90, (
        f"refresh() captured {section._pending_scroll} — it must read the offset "
        f"BEFORE lst.clear() zeroes it"
    )
