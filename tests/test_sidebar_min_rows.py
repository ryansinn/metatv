"""A sidebar section cannot be squeezed below the rows it needs.

Before this, one global 80px floor applied to every section, so the owner's
saved layout legally had History at 91px — about two rows — while Watch Queue
held 403px. The floor is now derived from each section's declared MIN_ROWS.
"""
from __future__ import annotations

import os
import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_floor_is_derived_from_declared_rows(_app) -> None:
    from metatv.gui.sidebar.base import CollapsibleSection

    class _Four(CollapsibleSection):
        MIN_ROWS = 4
        def create_content(self):  # noqa: D102
            pass

    class _Eight(_Four):
        MIN_ROWS = 8

    four = _Four.preferred_expanded_height(_Four)
    eight = _Eight.preferred_expanded_height(_Eight)
    assert eight > four, "more declared rows must buy more height"
    assert four >= CollapsibleSection.HEADER_H + 4 * CollapsibleSection.ROW_H


def test_history_can_no_longer_be_squeezed_to_two_rows(_app) -> None:
    """The specific regression: 91px for History.

    Now about the PREFERENCE rather than the floor. Automatic redistribution
    honours it, so nothing starves History to 91px on its own; only the user
    dragging the handle can take it lower, which is a deliberate act and the
    point of the second limit.
    """
    from metatv.gui.sidebar.base import CollapsibleSection
    from metatv.gui.sidebar.history import HistorySection

    floor = HistorySection.preferred_expanded_height(HistorySection)
    assert floor > 91, (
        f"History floor is {floor}px — the saved layout that starved it was 91px"
    )
    rows_that_fit = (floor - CollapsibleSection.HEADER_H) // CollapsibleSection.ROW_H
    assert rows_that_fit >= 4, f"only {rows_that_fit} rows fit at the floor"


def test_every_section_declares_a_floor_at_least_the_global_one(_app) -> None:
    from metatv.gui.sidebar import alerts, favorites, history, queue, recommended
    from metatv.gui.sidebar.base import _MIN_EXPANDED

    mods = (alerts, favorites, history, queue, recommended)
    seen = 0
    for mod in mods:
        for name in dir(mod):
            obj = getattr(mod, name)
            fn = getattr(obj, "preferred_expanded_height", None)
            if isinstance(obj, type) and callable(fn) and getattr(obj, "MIN_ROWS", None):
                assert fn(obj) >= _MIN_EXPANDED
                seen += 1
    assert seen >= 5, f"expected every section to declare MIN_ROWS; found {seen}"
