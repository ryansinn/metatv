"""The filter panel must hide AND come back (#280).

Owner: "filter panel in the menu only seems to turn off (but doesn't actually
disappear, just gets narrower) but cannot be turned back on again via the menu."

Both symptoms, one cause. ``filter_panel`` sets ``setMinimumWidth(160)``, so
``splitter.setSizes([0, …])`` never reaches 0 — Qt clamps to the minimum, which
is why it merely got narrower. And the old code chose its direction from that
measured size (``sizes[0] > 0``, still true at 160), so every subsequent toggle
took the hide branch again and the panel could never be restored.

Fixed by hiding the widget and taking direction from the persisted flag — the
actual state — rather than inferring it from geometry that cannot express "off".
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.gui.collapsible_splitter import CollapsibleSplitter
from metatv.gui.main_window_channels import _ChannelListMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Config:
    def __init__(self):
        self.filter_section_visible = True
        self.filter_panel_width = 220
        self.saves = 0

    def save(self):
        self.saves += 1


class _Host(_ChannelListMixin):
    """Real toggle_filters over a real splitter with the real minimum width."""

    def __init__(self):
        self.config = _Config()
        self.filter_panel = QWidget()
        self.filter_panel.setMinimumWidth(160)      # the constraint that broke it
        list_area = QWidget()
        self._inner_splitter = CollapsibleSplitter(Qt.Orientation.Horizontal)
        self._inner_splitter.addWidget(self.filter_panel)
        self._inner_splitter.addWidget(list_area)
        self._inner_splitter.setSizes([220, 780])
        self._inner_splitter.resize(1000, 600)
        self._inner_splitter.show()
        QApplication.processEvents()


def test_hiding_actually_hides_it(qapp):
    """Not "narrower" — gone."""
    host = _Host()

    host.toggle_filters()
    QApplication.processEvents()

    assert not host.filter_panel.isVisible(), (
        "the panel is still visible — a minimum width means splitter collapse "
        "can only ever shrink it"
    )
    assert host.config.filter_section_visible is False


def test_it_can_be_turned_back_on(qapp):
    """The half that was impossible before."""
    host = _Host()

    host.toggle_filters()          # off
    host.toggle_filters()          # on
    QApplication.processEvents()

    assert host.filter_panel.isVisible()
    assert host.config.filter_section_visible is True


def test_it_survives_repeated_toggling(qapp):
    """Off/on several times — the stuck-state bug only showed on the 2nd press."""
    host = _Host()

    for expected in (False, True, False, True, False, True):
        host.toggle_filters()
        QApplication.processEvents()
        assert host.config.filter_section_visible is expected
        assert host.filter_panel.isVisible() is expected


def test_the_users_width_is_restored_not_a_default(qapp):
    """Reopening should return the panel where the user left it."""
    host = _Host()
    host._inner_splitter.setSizes([340, 660])
    QApplication.processEvents()

    host.toggle_filters()          # captures 340 on the way out
    host.toggle_filters()
    QApplication.processEvents()

    # Approximately, not exactly: the splitter handle takes a couple of pixels,
    # so pinning 340 would fail for a reason that has nothing to do with the
    # behaviour under test (CLAUDE.md — never pin an exact px). What matters is
    # that it restored the USER's width rather than falling back to the 220
    # default, so assert it is near 340 and clearly not the default.
    assert abs(host.config.filter_panel_width - 340) <= 5, (
        f"restored to {host.config.filter_panel_width}px, nowhere near the "
        f"340px the user had set"
    )
    assert host.config.filter_panel_width != 220, "fell back to the default"


def test_direction_comes_from_state_not_geometry(qapp):
    """The root cause, pinned.

    A width clamped to the minimum must not read as "visible" — that inference
    is what made the toggle one-way.
    """
    host = _Host()
    host.config.filter_section_visible = False
    host.filter_panel.setVisible(False)
    host._inner_splitter.setSizes([160, 840])    # clamped, looks "open"
    QApplication.processEvents()

    host.toggle_filters()
    QApplication.processEvents()

    assert host.config.filter_section_visible is True, (
        "toggling from a hidden state must SHOW the panel, regardless of what "
        "the splitter reports"
    )
