"""EPG header two-row layout (0181).

The EPG header used to be a single horizontal row —
``[tab_bar] [stretch] [status_label] [refresh_btn]`` — so the long status text
and the Refresh button ate ~500px on the tab row and forced the ``QTabBar`` into
a ‹ › overflow-scroll state, hiding tabs.  It is now two stacked rows:

  Row 1 (full width):  ``[tab_bar] [stretch]``
  Row 2 (right-aligned): ``[stretch] [status_label] [refresh_btn]``

These tests construct the *real* ``EpgView`` widget offscreen and assert the new
structure — that ``status_label`` / ``refresh_btn`` are NOT layout-siblings of
``tab_bar`` in the same horizontal row, that the Refresh button sits *below* the
tab bar (mapped global y after show + grab), and that all three widgets still
exist and ``refresh_btn`` is still wired to the force-refresh handler.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout

from metatv.core.config import Config
from metatv.gui.epg_view import EpgView


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def epg_view(qapp, tmp_path):
    """A real EpgView built offscreen with a real Config + mocked db/epg_manager.

    ``_setup_ui`` (and every ``_build_*_tab`` it calls) reads config attributes
    and connects signals to real methods, but never touches the DB — so a
    MagicMock db/epg_manager is sufficient to exercise the header-build path.
    ``config_dir=tmp_path`` keeps any config write off the real user config.
    """
    config = Config(config_dir=tmp_path)
    view = EpgView(config, db=MagicMock(), epg_manager=MagicMock())
    try:
        yield view
    finally:
        view._executor.shutdown(wait=False)
        view.close()
        view.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header_of(view: EpgView):
    """The header QWidget — parent of the tab bar / status / refresh widgets."""
    header = view.tab_bar.parentWidget()
    # All three header widgets live under the same header widget.
    assert view.status_label.parentWidget() is header
    assert view.refresh_btn.parentWidget() is header
    return header


def _row_layouts(header):
    """Return the QHBoxLayout rows nested inside the header's QVBoxLayout."""
    top = header.layout()
    return [top.itemAt(i).layout() for i in range(top.count())
            if top.itemAt(i).layout() is not None]


def _widgets_in(row_layout):
    return [row_layout.itemAt(i).widget() for i in range(row_layout.count())
            if row_layout.itemAt(i).widget() is not None]


def _row_containing(rows, widget):
    for row in rows:
        if widget in _widgets_in(row):
            return row
    return None


# ---------------------------------------------------------------------------
# Structure: two stacked rows, widgets kept
# ---------------------------------------------------------------------------

def test_header_is_vbox_with_two_hbox_rows(epg_view):
    header = _header_of(epg_view)
    assert isinstance(header.layout(), QVBoxLayout)
    rows = _row_layouts(header)
    assert len(rows) == 2, "header must have exactly two stacked rows"
    assert all(isinstance(r, QHBoxLayout) for r in rows)


def test_header_keeps_12_8_margins(epg_view):
    """The two-row restructure keeps the original 12/8 header margins."""
    m = _header_of(epg_view).layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (12, 8, 12, 8)


def test_status_and_refresh_not_siblings_of_tab_bar_row(epg_view):
    """Refresh + status must NOT share the tab bar's horizontal row."""
    rows = _row_layouts(_header_of(epg_view))

    tab_row = _row_containing(rows, epg_view.tab_bar)
    status_row = _row_containing(rows, epg_view.refresh_btn)
    assert tab_row is not None and status_row is not None
    assert tab_row is not status_row, "refresh must be on a separate row from the tabs"

    tab_row_widgets = _widgets_in(tab_row)
    assert epg_view.refresh_btn not in tab_row_widgets
    assert epg_view.status_label not in tab_row_widgets

    # Row 2 carries both status + refresh, and NOT the tab bar.
    status_row_widgets = _widgets_in(status_row)
    assert epg_view.status_label in status_row_widgets
    assert epg_view.tab_bar not in status_row_widgets


def test_row1_tab_bar_trailing_stretch_row2_leading_stretch(epg_view):
    """Row 1: tab_bar then trailing stretch.  Row 2: leading stretch (right-aligned)."""
    rows = _row_layouts(_header_of(epg_view))
    tab_row = _row_containing(rows, epg_view.tab_bar)
    status_row = _row_containing(rows, epg_view.refresh_btn)

    # Row 1 ends with a stretch → tab bar gets the full width on the left.
    assert tab_row.itemAt(tab_row.count() - 1).spacerItem() is not None
    # Row 2 begins with a stretch → status + refresh are right-aligned.
    assert status_row.itemAt(0).spacerItem() is not None


def test_all_header_widgets_still_exist(epg_view):
    assert epg_view.tab_bar is not None
    assert epg_view.status_label is not None
    assert epg_view.refresh_btn is not None
    assert epg_view.tab_bar.count() == 7  # all tabs preserved


# ---------------------------------------------------------------------------
# Geometry: refresh sits BELOW the tab bar (tab bar spans header width)
# ---------------------------------------------------------------------------

def test_refresh_button_sits_below_tab_bar(epg_view, qapp):
    """After a real layout pass, the Refresh button is vertically below the tab bar.

    A single-row header would place them side-by-side (same y band).  Stacked, the
    Refresh button's top edge is at or below the tab bar's bottom edge — proving the
    tab bar now owns the full width of its own row.
    """
    epg_view.resize(900, 500)
    epg_view.show()
    qapp.processEvents()
    epg_view.grab()          # force a synchronous layout + paint
    qapp.processEvents()

    tab_bottom_y = epg_view.tab_bar.mapToGlobal(
        epg_view.tab_bar.rect().bottomLeft()).y()
    refresh_top_y = epg_view.refresh_btn.mapToGlobal(
        epg_view.refresh_btn.rect().topLeft()).y()

    assert refresh_top_y >= tab_bottom_y, (
        f"Refresh top ({refresh_top_y}) should be at/below tab-bar bottom "
        f"({tab_bottom_y}) — they must not share a row"
    )


# ---------------------------------------------------------------------------
# Wiring: refresh_btn still triggers the force-refresh handler
# ---------------------------------------------------------------------------

def test_refresh_button_still_wired_to_force_refresh(epg_view):
    """Clicking Refresh still drives EpgManager.force_refresh_provider per source."""
    epg_view._provider_ids = ["p1", "p2"]
    epg_view.refresh_btn.click()
    calls = [c.args[0] for c in epg_view.epg_manager.force_refresh_provider.call_args_list]
    assert calls == ["p1", "p2"]
