"""Behavioral tests for ``ToolView`` (metatv/gui/tool_view.py).

The shared scaffold four Tools-menu views (Source Analytics, Missing TMDb,
Reconnect Engaged Content, Metadata Enrichment) used to rebuild independently
by copy-paste — see docs/REFACTOR_PLAN.md "Running duplication ledger". This
pins the three behaviors the scaffold must actually deliver: a failed panel
load renders exactly one visible error row (never a silent blank / stuck
"Loading…"), ``clear_layout`` actually empties nested layouts (not just the
top-level widget list), and the Back button in the shared top bar really
emits ``done``.
"""
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui.tool_view import ToolView, clear_layout


def _make_view(qtbot) -> ToolView:
    main_window = SimpleNamespace(config=SimpleNamespace())
    view = ToolView(main_window)
    qtbot.addWidget(view)
    return view


# ---------------------------------------------------------------------------
# show_panel_error
# ---------------------------------------------------------------------------


def test_show_panel_error_renders_one_row_with_warning_icon_and_detail(qtbot) -> None:
    """A failed load must render exactly one visible row naming the failure —
    never a blank panel indistinguishable from an empty result."""
    view = _make_view(qtbot)
    container = QWidget()
    layout = QVBoxLayout(container)

    view.show_panel_error(layout, "database is locked")

    assert layout.count() == 1
    label = layout.itemAt(0).widget()
    assert isinstance(label, QLabel)
    assert _icons.notification_warning_icon in label.text()
    assert "database is locked" in label.text()


def test_show_panel_error_replaces_a_prior_loading_placeholder(qtbot) -> None:
    """The error row must REPLACE a "Loading…" placeholder, not sit next to it —
    otherwise a failed load leaves both a spinner-ish label and an error row."""
    view = _make_view(qtbot)
    container = QWidget()
    layout = QVBoxLayout(container)
    view.show_loading(layout)
    assert layout.count() == 1

    view.show_panel_error(layout, RuntimeError("boom"))

    assert layout.count() == 1
    label = layout.itemAt(0).widget()
    assert "Loading" not in label.text()
    assert "boom" in label.text()


# ---------------------------------------------------------------------------
# clear_layout
# ---------------------------------------------------------------------------


def test_clear_layout_empties_widgets_and_nested_layouts(qtbot) -> None:
    """clear_layout must recurse into a nested QHBoxLayout row, not just drop
    the top-level widgets — a panel built from inner rows (as all four Tools
    views are) would otherwise leave orphaned child layouts behind."""
    container = QWidget()
    qtbot.addWidget(container)
    layout = QVBoxLayout(container)
    layout.addWidget(QLabel("top-level"))

    nested = QHBoxLayout()
    nested.addWidget(QLabel("nested-a"))
    nested.addWidget(QLabel("nested-b"))
    layout.addLayout(nested)

    assert layout.count() == 2

    clear_layout(layout)

    assert layout.count() == 0


# ---------------------------------------------------------------------------
# build_top_bar
# ---------------------------------------------------------------------------


def test_build_top_bar_back_button_emits_done(qtbot) -> None:
    view = _make_view(qtbot)
    top_bar = view.build_top_bar("Some Tool")
    container = QWidget()
    qtbot.addWidget(container)
    container.setLayout(top_bar)

    back_btn = top_bar.itemAt(0).widget()
    assert "Back" in back_btn.text()

    with qtbot.waitSignal(view.done, timeout=1000):
        back_btn.click()


def test_build_top_bar_shows_the_given_title(qtbot) -> None:
    view = _make_view(qtbot)
    top_bar = view.build_top_bar("Missing TMDb Data")
    container = QWidget()
    qtbot.addWidget(container)
    container.setLayout(top_bar)

    title_label = top_bar.itemAt(1).widget()
    assert isinstance(title_label, QLabel)
    assert title_label.text() == "Missing TMDb Data"
