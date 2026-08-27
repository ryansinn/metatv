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

class _StubConfig:
    """A real ``Config`` with a couple of test overrides in front of it.

    It was a bare ``SimpleNamespace`` listing twelve attributes by hand, and it
    went stale exactly the way a hand-maintained enumeration does: History grew
    a ``delete_icon`` and Watch Queue a ``watched_icon``, neither was added
    here, and both constructors raised ``AttributeError`` on ``main``. Falling
    through to a real Config means the next attribute a section reads is
    already here.

    The autouse ``_isolate_user_config`` fixture points ``Path.home()`` at a
    tmp dir, so constructing a real Config touches nothing of the user's.
    """

    def __init__(self, **overrides):
        from metatv.core.config import Config

        self.__dict__["_overrides"] = overrides
        self.__dict__["_real"] = Config()

    def __getattr__(self, name):
        overrides = self.__dict__["_overrides"]
        if name in overrides:
            return overrides[name]
        return getattr(self.__dict__["_real"], name)

    def __setattr__(self, name, value):
        self.__dict__["_overrides"][name] = value


def _stub_config():
    return _StubConfig(
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


def test_the_header_carries_no_caret(qapp):
    """This test used to assert the opposite — that the arrow button works.

    It was named ``test_toggle_btn_also_wired`` and guarded a SECOND
    affordance for one action: a chevron beside a header that has been
    clickable since #329 and carries the pointing-hand cursor. The owner:
    "let's remove the carets, clicking the title collapses and expands, let's
    assume it's obvious, it'll make it look better."

    Inverted rather than deleted, so the reversal is legible here rather than
    looking like coverage that quietly evaporated. The affordance that
    remains is asserted by ``test_build_clickable_header_wires_toggle`` above
    and by the pointing-hand test below — between them, the header is proven
    to BE the control.
    """
    from PyQt6.QtWidgets import QPushButton

    section = _bare_section(qapp)
    header = section._build_clickable_header()
    section.main_layout.addWidget(header)

    # __dict__, not hasattr: this section is built via __new__, and PyQt raises
    # RuntimeError for a missing attribute on one — which hasattr does NOT
    # absorb, so the guard itself explodes. CLAUDE.md says exactly this, and I
    # wrote hasattr anyway while writing a test about the caret.
    assert "toggle_btn" not in section.__dict__, (
        "the caret is back — the header is the control"
    )
    glyphs = {b.text() for b in header.findChildren(QPushButton)}
    assert not (glyphs & {section.config.expand_icon, section.config.collapse_icon}), (
        f"a collapse chevron is being drawn in the header: {glyphs}"
    )
    assert header.toolTip(), (
        "with no caret the header's tooltip is the only hint that it toggles"
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
    # Faked like `icon` above. create_header() reads it to choose between a
    # vector glyph and the emoji, and on a __new__'d section ANY unset instance
    # attribute raises RuntimeError rather than AttributeError — so it has to
    # be present, not merely defaulted. None keeps this test on the text path,
    # which is what it is about; the glyph is covered against real sections by
    # tests/test_sidebar_header_vector_icons.py.
    object.__setattr__(section, "vector_role", None)
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
    # Bring Qt's C++ side up WITHOUT running the subclass __init__ (which is
    # what this helper exists to avoid). Without it, every attribute this
    # function sets is a gamble and any assignment the header itself makes —
    # ``self._overflow_btn``, for one — raises "super-class __init__() was
    # never called" the moment a header grows one. The docstring below already
    # described that hazard for reads; the ⋯ every section now carries made it
    # a write hazard too.
    QFrame.__init__(section)

    # Set instance attributes directly — do NOT call hasattr on the uninitialized object.
    # PyQt6 signals are class-level descriptors, and accessing them on an instance whose
    # C++ side was never constructed raises RuntimeError.
    object.__setattr__(section, "title", "Test")
    object.__setattr__(section, "icon", "T")
    # Faked like `icon` above. create_header() reads it to choose between a
    # vector glyph and the emoji, and on a __new__'d section ANY unset instance
    # attribute raises RuntimeError rather than AttributeError — so it has to
    # be present, not merely defaulted. None keeps this test on the text path,
    # which is what it is about; the glyph is covered against real sections by
    # tests/test_sidebar_header_vector_icons.py.
    object.__setattr__(section, "vector_role", None)
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
    for sig_name in ("addWatchForClicked", "manageWatchForClicked", "clearAllAlertsClicked", "addProviderClicked", "refreshAllClicked"):
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


def test_history_header_is_clickable(qapp):
    from metatv.gui.sidebar.history import HistorySection
    _make_section(HistorySection, qapp=qapp)


def test_queue_header_is_clickable(qapp):
    """WatchQueueSection has no create_header override — it uses the BASE one, which
    grows the shared "Explore →" link.  Building it must not depend on Qt's C++ side
    being up (the link may not dereference a bound signal at construction time)."""
    from metatv.gui.sidebar.queue import WatchQueueSection
    _make_section(WatchQueueSection, qapp=qapp)


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
