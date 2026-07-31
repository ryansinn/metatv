"""EPG global bottom status bar (0183).

The EPG header used to carry the source-freshness status text and the Refresh
button (originally on the tab row, then on a second stacked row beneath it —
0181).  Both now live on a persistent GLOBAL bottom bar below the stacked
content area, right-aligned, so the whole header width belongs to the tab bar
and Refresh is reachable from *every* tab:

  Header (single row):  ``[tab_bar] [stretch]``
  Bottom bar (global):  ``[browse_stats] [stretch] [status_label] [refresh_btn]``

The Browse "###,### programmes" count (``browse_stats``) was relocated out of the
Browse tab page into that same bottom bar's left slot; because it is global now,
switching to a non-Browse tab blanks it.

These tests construct the *real* ``EpgView`` widget offscreen and assert the new
structure — that ``status_label`` / ``refresh_btn`` / ``browse_stats`` are NOT
children of the tab-bar header, that all three share a bottom-bar parent that
sits below ``self.stack``, that the bottom bar orders them count-left /
status+refresh-right, that Refresh is still wired to the force-refresh handler,
and that leaving the Browse tab clears the programmes count.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest

from PyQt6.QtWidgets import QApplication, QHBoxLayout

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
    MagicMock db/epg_manager is sufficient to exercise the header + bottom-bar
    build path.  ``config_dir=tmp_path`` keeps any config write off the real
    user config.
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
    """The header QWidget — parent of the tab bar."""
    return view.tab_bar.parentWidget()


def _bottom_bar_of(view: EpgView):
    """The global bottom-bar QWidget — parent of status/refresh/browse_stats."""
    return view.refresh_btn.parentWidget()


def _widgets_in(layout):
    return [layout.itemAt(i).widget() for i in range(layout.count())
            if layout.itemAt(i).widget() is not None]


# ---------------------------------------------------------------------------
# Structure: single-row header, three widgets moved to the global bottom bar
# ---------------------------------------------------------------------------

def test_header_is_a_single_tabs_row(epg_view):
    """The header carries only the tab bar — no status / refresh / count."""
    header = _header_of(epg_view)
    assert isinstance(header.layout(), QHBoxLayout)

    header_widgets = _widgets_in(header.layout())
    assert epg_view.tab_bar in header_widgets
    assert epg_view.status_label not in header_widgets
    assert epg_view.refresh_btn not in header_widgets
    assert epg_view.browse_stats not in header_widgets

    # And none of the relocated widgets are parented under the header.
    for w in (epg_view.status_label, epg_view.refresh_btn, epg_view.browse_stats):
        assert w.parentWidget() is not header


def test_status_refresh_and_count_share_the_bottom_bar(epg_view):
    """status_label, refresh_btn and browse_stats live together in one bottom bar."""
    bottom = _bottom_bar_of(epg_view)
    assert bottom is not _header_of(epg_view)
    assert epg_view.status_label.parentWidget() is bottom
    assert epg_view.refresh_btn.parentWidget() is bottom
    assert epg_view.browse_stats.parentWidget() is bottom
    # The tab bar is NOT in the bottom bar.
    assert epg_view.tab_bar not in _widgets_in(bottom.layout())


def test_bottom_bar_sits_below_the_stack(epg_view):
    """The bottom bar is added to the view root layout after (below) self.stack."""
    root = epg_view.layout()
    bottom = _bottom_bar_of(epg_view)
    stack_idx = root.indexOf(epg_view.stack)
    bottom_idx = root.indexOf(bottom)
    assert stack_idx != -1 and bottom_idx != -1
    assert bottom_idx > stack_idx, "bottom bar must come after the stack in the root layout"


def test_bottom_bar_orders_count_left_status_refresh_right(epg_view):
    """Layout order: [browse_stats] [stretch] [status_label] [refresh_btn]."""
    layout = _bottom_bar_of(epg_view).layout()

    # Widgets appear in this left-to-right order.
    assert _widgets_in(layout) == [
        epg_view.browse_stats,
        epg_view.status_label,
        epg_view.refresh_btn,
    ]

    # A stretch spacer sits between the left count and the right status/refresh,
    # so the status text + Refresh button are right-aligned.
    spacer_indices = [i for i in range(layout.count())
                      if layout.itemAt(i).spacerItem() is not None]
    count_index = next(i for i in range(layout.count())
                       if layout.itemAt(i).widget() is epg_view.browse_stats)
    status_index = next(i for i in range(layout.count())
                        if layout.itemAt(i).widget() is epg_view.status_label)
    assert any(count_index < s < status_index for s in spacer_indices)


def test_all_bar_widgets_still_exist(epg_view):
    assert epg_view.tab_bar is not None
    assert epg_view.status_label is not None
    assert epg_view.refresh_btn is not None
    assert epg_view.browse_stats is not None
    assert epg_view.tab_bar.count() == 7  # all tabs preserved


# ---------------------------------------------------------------------------
# Geometry: the bottom bar's Refresh button is below the tab bar (full-width tabs)
# ---------------------------------------------------------------------------

def test_refresh_button_sits_below_tab_bar(epg_view, qapp):
    """After a real layout pass, Refresh is below the tab bar and left of nothing.

    A header-embedded control would share the tab row's y band.  In the bottom
    bar it is well below the tab bar, and the count (browse_stats) is to its left.
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
        f"({tab_bottom_y}) — it lives in the bottom bar, not the header"
    )

    # Count is on the left, Refresh on the right of the same bottom bar.
    count_left_x = epg_view.browse_stats.mapToGlobal(
        epg_view.browse_stats.rect().topLeft()).x()
    refresh_left_x = epg_view.refresh_btn.mapToGlobal(
        epg_view.refresh_btn.rect().topLeft()).x()
    assert count_left_x < refresh_left_x, "programmes count must be left of Refresh"


# ---------------------------------------------------------------------------
# Wiring: refresh_btn still triggers the force-refresh handler
# ---------------------------------------------------------------------------

def test_refresh_button_still_wired_to_force_refresh(epg_view):
    """Clicking Refresh still drives EpgManager.force_refresh_provider per source."""
    epg_view._provider_ids = ["p1", "p2"]
    epg_view.refresh_btn.click()
    calls = [c.args[0] for c in epg_view.epg_manager.force_refresh_provider.call_args_list]
    assert calls == ["p1", "p2"]


# ---------------------------------------------------------------------------
# Behavior: the global count blanks when leaving the Browse tab
# ---------------------------------------------------------------------------

def test_leaving_browse_tab_clears_the_programmes_count(epg_view):
    """browse_stats is global now — switching to a non-Browse tab blanks it.

    _provider_ids is empty in this fixture, so the reload triggered by the tab
    switch short-circuits without touching the DB; only the clear runs.
    """
    epg_view.browse_stats.setText("123,456 programmes")
    assert epg_view.browse_stats.text() != ""

    # On Now (index 3) is not the Browse tab (index 4).
    assert epg_view._BROWSE_TAB_INDEX == 4
    epg_view.tab_bar.setCurrentIndex(3)   # fires _on_tab_changed(3)

    assert epg_view.browse_stats.text() == ""
