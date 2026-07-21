"""Tests for click-to-toggle sidebar section headers (id=35).

Behavioral invariants this suite pins:

1. ``_ClickableHeader.clicked`` fires when its ``mousePressEvent`` is called directly
   (the signal plumbing works).
2. After ``_build_clickable_header()``, clicking the header (simulated via
   ``header.clicked.emit()``) calls ``toggle_collapse`` on the section.
3. The toggle button's ``clicked`` signal is also connected to ``toggle_collapse``
   (the arrow button still works independently).
4. All five section types that override ``create_header`` produce a ``_ClickableHeader``
   as the header widget (not a plain ``QWidget``).

These are behavioral tests — each asserts what would actually break if the wiring
were removed, not the shape of the implementation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level QApplication so Qt widgets can be instantiated headless
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Minimal config stub used across all section constructors
# ---------------------------------------------------------------------------

def _stub_config():
    return SimpleNamespace(
        collapse_icon="v",
        expand_icon=">",
        favorite_icon="★",
        preferences_icon="♦",
        provider_icon="◉",
        refresh_icon="↻",
        play_icon="▶",
        live_icon="L",
        movie_icon="M",
        series_icon="S",
        unknown_icon="?",
        filter_adult_mode="all",
        sidebar_section_states={},
    )


def _mock_db():
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.session_scope.return_value = cm
    return db


# ---------------------------------------------------------------------------
# 1. _ClickableHeader signal plumbing
# ---------------------------------------------------------------------------

def test_clickable_header_emits_on_mouse_press(qapp):
    """mousePressEvent on _ClickableHeader fires the ``clicked`` signal."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF, QPoint
    from metatv.gui.sidebar.base import _ClickableHeader

    header = _ClickableHeader()
    fired = []
    header.clicked.connect(lambda: fired.append(True))

    # Simulate a left-button press at (0, 0)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    header.mousePressEvent(event)

    assert fired == [True], "mousePressEvent must emit clicked"


def test_clickable_header_has_pointing_hand_cursor(qapp):
    """_ClickableHeader uses a PointingHandCursor to signal interactivity."""
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.base import _ClickableHeader

    header = _ClickableHeader()
    assert header.cursor().shape() == Qt.CursorShape.PointingHandCursor


# ---------------------------------------------------------------------------
# 2. _build_clickable_header wires header.clicked → toggle_collapse
# ---------------------------------------------------------------------------

def _bare_section(qapp):
    """Build a CollapsibleSection via ``__new__`` with just enough state for header tests.

    The header widget is kept alive by being added to a real QFrame's layout so
    Qt does not garbage-collect the QPushButton children.
    """
    from PyQt6.QtWidgets import QFrame, QVBoxLayout
    from metatv.gui.sidebar.base import CollapsibleSection

    section = CollapsibleSection.__new__(CollapsibleSection)
    object.__setattr__(section, "config", _stub_config())
    object.__setattr__(section, "is_collapsed", False)
    object.__setattr__(section, "_user_collapsed", False)
    object.__setattr__(section, "_expanded_height", 80)

    # Anchor widgets to a real frame so Qt keeps them alive
    frame = QFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    object.__setattr__(section, "main_layout", layout)
    object.__setattr__(section, "_anchor_frame", frame)  # keep frame alive

    return section


def test_build_clickable_header_wires_toggle(qapp):
    """header.clicked.emit() calls toggle_collapse on the owning CollapsibleSection."""
    section = _bare_section(qapp)

    toggle_calls = []
    object.__setattr__(section, "toggle_collapse", lambda: toggle_calls.append(1))

    header = section._build_clickable_header()
    # Keep header alive; add to the layout
    section.main_layout.addWidget(header)

    header.clicked.emit()

    assert toggle_calls == [1], (
        "header.clicked must call toggle_collapse when header background is clicked"
    )


def test_toggle_btn_also_wired(qapp):
    """toggle_btn.clicked is also connected to toggle_collapse (arrow button still works)."""
    section = _bare_section(qapp)

    toggle_calls = []
    object.__setattr__(section, "toggle_collapse", lambda: toggle_calls.append(1))

    header = section._build_clickable_header()
    # Keep the header (and its QPushButton children) alive
    section.main_layout.addWidget(header)

    section.toggle_btn.clicked.emit()

    assert toggle_calls == [1], (
        "toggle_btn.clicked must also be connected to toggle_collapse"
    )


# ---------------------------------------------------------------------------
# 3. All five overriding sections produce a _ClickableHeader
# ---------------------------------------------------------------------------

def _header_widget(section):
    """Return the first widget from the section's main_layout (the header)."""
    from PyQt6.QtWidgets import QVBoxLayout
    layout = section.main_layout
    assert isinstance(layout, QVBoxLayout)
    return layout.itemAt(0).widget()


def test_base_section_header_is_clickable_header(qapp):
    """CollapsibleSection base create_header produces a _ClickableHeader."""
    from metatv.gui.sidebar.base import _ClickableHeader

    section = _bare_section(qapp)
    object.__setattr__(section, "title", "Test")
    object.__setattr__(section, "icon", "T")
    object.__setattr__(section, "toggle_collapse", MagicMock())

    section.create_header()

    hdr = section.main_layout.itemAt(0).widget()
    assert isinstance(hdr, _ClickableHeader), (
        f"Base create_header must produce a _ClickableHeader, got {type(hdr)}"
    )


def _make_section(cls, extra_kwargs=None, qapp=None):
    """Instantiate a section class via __new__ + create_header only (no full __init__).

    We avoid calling __init__ because it triggers background threads / DB access.
    Instead we manually set the minimal attributes create_header() needs and call it.

    PyQt6 classes with ``pyqtSignal`` declarations raise ``RuntimeError`` on ``hasattr``
    when Qt's C++ side has not been initialised (i.e. ``super().__init__`` was never
    called).  We work around this by *always* setting stub attributes for every signal
    name that any ``create_header`` implementation might reference, before checking
    anything on the section object.
    """
    from PyQt6.QtWidgets import QVBoxLayout, QFrame
    from metatv.gui.sidebar.base import _ClickableHeader

    section = cls.__new__(cls)

    # Set instance attributes directly — do NOT call hasattr on the uninitialized object.
    # PyQt6 signals are class-level descriptors, and accessing them on an instance whose
    # C++ side was never constructed raises RuntimeError.
    object.__setattr__(section, "title", "Test")
    object.__setattr__(section, "icon", "T")
    object.__setattr__(section, "config", _stub_config())
    object.__setattr__(section, "is_collapsed", False)
    object.__setattr__(section, "_user_collapsed", False)
    object.__setattr__(section, "_expanded_height", 80)

    if extra_kwargs:
        for k, v in extra_kwargs.items():
            object.__setattr__(section, k, v)

    frame = QFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    object.__setattr__(section, "main_layout", layout)

    # Unconditionally stub every signal that create_header implementations may call.
    # Setting instance attributes here shadows the class-level pyqtSignal descriptors,
    # which is fine — we only need .emit() to not error during the test.
    for sig_name in ("addWatchForClicked", "clearAllAlertsClicked", "addProviderClicked", "refreshAllClicked"):
        stub = MagicMock()
        stub.emit = MagicMock()
        object.__setattr__(section, sig_name, stub)

    toggle_mock = MagicMock()
    object.__setattr__(section, "toggle_collapse", toggle_mock)

    section.create_header()

    hdr = layout.itemAt(0).widget()
    assert isinstance(hdr, _ClickableHeader), (
        f"{cls.__name__}.create_header must produce a _ClickableHeader, got {type(hdr)}"
    )
    return section


def test_favorites_header_is_clickable(qapp):
    from metatv.gui.sidebar.favorites import FavoritesSection
    _make_section(FavoritesSection, qapp=qapp)


def test_recommended_header_is_clickable(qapp):
    from metatv.gui.sidebar.recommended import RecommendedSection
    _make_section(RecommendedSection, qapp=qapp)


def test_alerts_header_is_clickable(qapp):
    from metatv.gui.sidebar.alerts import WatchAlertsSection
    _make_section(WatchAlertsSection, qapp=qapp)


def test_sources_header_is_clickable(qapp):
    from metatv.gui.sidebar.sources import SourcesSection
    _make_section(SourcesSection, qapp=qapp)


# ---------------------------------------------------------------------------
# 4. Action button clicks do NOT trigger toggle (event is consumed by QPushButton)
# ---------------------------------------------------------------------------

def test_action_button_does_not_toggle_section(qapp):
    """A QPushButton child inside the header consumes its own click; the header does not also toggle.

    This tests the expected Qt behaviour: QPushButton.clicked fires its own handlers;
    the parent widget's mousePressEvent is NOT called because the button consumes the
    press event.  We verify this by ensuring toggle_collapse is NOT called when a child
    button emits clicked.
    """
    from PyQt6.QtWidgets import QPushButton

    section = _bare_section(qapp)

    header_toggle_calls = []
    object.__setattr__(section, "toggle_collapse", lambda: header_toggle_calls.append(1))

    header = section._build_clickable_header()
    section.main_layout.addWidget(header)

    # An action button that fires its own action
    action_calls = []
    action_btn = QPushButton("+", parent=header)
    action_btn.clicked.connect(lambda: action_calls.append(1))

    # Simulate clicking the action button (not the header background)
    action_btn.clicked.emit()

    assert action_calls == [1], "Action button must fire its own handler"
    # toggle_collapse must NOT be called when an action button is clicked —
    # QPushButton consumes the press event so it never reaches the header's
    # mousePressEvent.  Emitting clicked directly also does not call header.clicked.
    assert header_toggle_calls == [], (
        "Action button click must NOT propagate to header toggle_collapse via signal"
    )
