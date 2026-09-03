"""Right-click a sidebar section header -> Hide / Sidebar settings… (#542).

A SHORTCUT over the existing mechanism: the menu only emits signals
(``hideRequested``/``sidebarSettingsRequested``); ``MainWindow`` (via
``_NavMixin._hide_sidebar_section``) does the actual
``config.sidebar_visible_sections`` mutation and reapplies it through the one
chokepoint, ``_apply_sidebar_visibility`` — never a direct ``setVisible``.

Mirrors ``test_clickable_section_headers.py``'s local-helper pattern (no
conftest factory exists yet for sidebar-visibility test doubles): a bare
``CollapsibleSection``/subclass built via ``__new__`` for the header/menu
tests, and a bare ``_NavMixin`` (mirroring ``test_stream_recovery_ux.py``'s
``_FavoritesMixin.__new__`` host) driving the REAL ``_hide_sidebar_section``
for the mutation tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.gui import deferred_config_save as _cfgsave


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _stub_config():
    """A real Config with the couple of overrides section constructors read."""
    from metatv.core.config import Config

    class _StubConfig:
        def __init__(self, **overrides):
            self.__dict__["_overrides"] = overrides
            self.__dict__["_real"] = Config()

        def __getattr__(self, name):
            overrides = self.__dict__["_overrides"]
            return overrides[name] if name in overrides else getattr(self.__dict__["_real"], name)

        def __setattr__(self, name, value):
            self.__dict__["_overrides"][name] = value

    return _StubConfig(filter_adult_mode="all", sidebar_section_states={})


def _make_section(cls, qapp, extra_kwargs=None):
    """Build *cls* via ``__new__`` + ``create_header()`` only — mirrors
    ``test_clickable_section_headers.py``'s helper of the same name."""
    from PyQt6.QtWidgets import QFrame, QVBoxLayout
    from metatv.gui.sidebar.base import _ClickableHeader

    section = cls.__new__(cls)
    QFrame.__init__(section)

    object.__setattr__(section, "title", "Test Section")
    object.__setattr__(section, "icon", "T")
    object.__setattr__(section, "vector_role", None)
    object.__setattr__(section, "config", _stub_config())
    object.__setattr__(section, "is_collapsed", False)
    object.__setattr__(section, "_user_collapsed", False)
    object.__setattr__(section, "_expanded_height", 80)

    for k, v in (extra_kwargs or {}).items():
        object.__setattr__(section, k, v)

    frame = QFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    object.__setattr__(section, "main_layout", layout)
    # Anchor frame alive past this function's return — the caller inspects
    # the header, and without a live Python ref to `frame` the whole tree
    # (frame -> layout -> header) is GC'd the moment this function exits.
    object.__setattr__(section, "_anchor_frame", frame)

    for sig_name in ("addWatchForClicked", "manageWatchForClicked", "clearAllAlertsClicked",
                     "addProviderClicked", "refreshAllClicked"):
        stub = MagicMock()
        stub.emit = MagicMock()
        object.__setattr__(section, sig_name, stub)

    object.__setattr__(section, "toggle_collapse", MagicMock())
    object.__setattr__(section, "hideRequested", MagicMock())
    object.__setattr__(section, "sidebarSettingsRequested", MagicMock())

    section.create_header()

    hdr = layout.itemAt(0).widget()
    assert isinstance(hdr, _ClickableHeader)
    return section, hdr


# ---------------------------------------------------------------------------
# 1. Every section's header opens the two-item menu
# ---------------------------------------------------------------------------

_SECTION_CLASSES = []
for _mod, _name in (
    ("metatv.gui.sidebar.base", "CollapsibleSection"),
    ("metatv.gui.sidebar.favorites", "FavoritesSection"),
    ("metatv.gui.sidebar.recommended", "RecommendedSection"),
    ("metatv.gui.sidebar.history", "HistorySection"),
    ("metatv.gui.sidebar.queue", "WatchQueueSection"),
    ("metatv.gui.sidebar.alerts", "WatchAlertsSection"),
    ("metatv.gui.sidebar.sources", "SourcesSection"),
):
    import importlib
    _SECTION_CLASSES.append(getattr(importlib.import_module(_mod), _name))


@pytest.mark.parametrize("cls", _SECTION_CLASSES, ids=lambda c: c.__name__)
def test_header_context_menu_has_hide_and_settings_actions(cls, qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu

    section, hdr = _make_section(cls, qapp)

    captured = {}

    def fake_exec(self, pos):
        captured["texts"] = [a.text() for a in self.actions()]
        return None  # no selection — neither signal should fire

    assert hdr.contextMenuPolicy().name == "CustomContextMenu"

    with patch.object(QMenu, "exec", fake_exec):
        hdr.customContextMenuRequested.emit(QPoint(3, 3))

    assert captured["texts"] == ["Hide Test Section", "Sidebar settings…"], (
        f"{cls.__name__}: unexpected menu actions {captured.get('texts')}"
    )


def test_choosing_hide_emits_hideRequested(qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    from metatv.gui.sidebar.base import CollapsibleSection

    section, hdr = _make_section(CollapsibleSection, qapp)

    def fake_exec(self, pos):
        return self.actions()[0]  # "Hide …"

    with patch.object(QMenu, "exec", fake_exec):
        hdr.customContextMenuRequested.emit(QPoint(3, 3))

    section.hideRequested.emit.assert_called_once()
    section.sidebarSettingsRequested.emit.assert_not_called()


def test_choosing_settings_emits_sidebarSettingsRequested(qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    from metatv.gui.sidebar.base import CollapsibleSection

    section, hdr = _make_section(CollapsibleSection, qapp)

    def fake_exec(self, pos):
        return self.actions()[1]  # "Sidebar settings…"

    with patch.object(QMenu, "exec", fake_exec):
        hdr.customContextMenuRequested.emit(QPoint(3, 3))

    section.sidebarSettingsRequested.emit.assert_called_once()
    section.hideRequested.emit.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Right-click does not toggle collapse
# ---------------------------------------------------------------------------

def test_right_click_does_not_toggle_collapse(qapp):
    """``_ClickableHeader.mousePressEvent`` fires ``clicked`` (-> toggle_collapse)
    on the LEFT button only. Collapse is triggered by ``header.clicked``, wired
    in ``_build_clickable_header`` (``header.clicked.connect(self.toggle_collapse)``);
    a right-click reaches the header's ``mousePressEvent`` exactly like a left
    one (Qt delivers press events for every button), so without the button
    check this would ALSO toggle collapse in addition to opening the menu.
    """
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from metatv.gui.sidebar.base import _ClickableHeader

    header = _ClickableHeader()
    fired = []
    header.clicked.connect(lambda: fired.append(True))

    right = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(5, 5),
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    header.mousePressEvent(right)
    assert fired == [], "right-click must not fire `clicked` (would toggle collapse)"

    left = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    header.mousePressEvent(left)
    assert fired == [True], "left-click must still fire `clicked` (toggles collapse)"


# ---------------------------------------------------------------------------
# 2 & 3. _hide_sidebar_section: config mutation + apply + Undo ordering
# ---------------------------------------------------------------------------

def _make_host(tmp_path, order):
    """A bare ``_NavMixin`` driving the REAL ``_hide_sidebar_section`` —
    mirrors ``test_stream_recovery_ux.py``'s ``_FavoritesMixin.__new__`` host.
    """
    from metatv.core.config import Config
    from metatv.gui.main_window_nav import _NavMixin

    host = _NavMixin.__new__(_NavMixin)
    host.config = Config(config_dir=tmp_path)
    host.config.sidebar_sections = list(order)
    host.config.sidebar_visible_sections = list(order)
    host.sidebar_sections = {sid: SimpleNamespace(title=sid.capitalize()) for sid in order}
    host._apply_sidebar_visibility = MagicMock()
    host.notification_manager = MagicMock()
    return host


def test_hide_sidebar_section_removes_saves_and_reapplies(tmp_path):
    host = _make_host(tmp_path, ["a", "b", "c"])

    host._hide_sidebar_section("b")

    assert host.config.sidebar_visible_sections == ["a", "c"]
    host._apply_sidebar_visibility.assert_called_once()

    # The write settles through the deferred-save chokepoint (CFG-10) rather
    # than writing synchronously; flush forces it now so the file on disk can
    # be checked without waiting out the real timer.
    assert _cfgsave.flush(host) is True

    # .save() really ran (not mocked): the file it writes now exists on disk
    # and holds the mutated list — proving this isn't just an in-memory
    # attribute assignment.
    import yaml
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert on_disk["sidebar_visible_sections"] == ["a", "c"]


def test_hide_sidebar_section_toast_offers_undo(tmp_path):
    host = _make_host(tmp_path, ["a", "b", "c"])

    host._hide_sidebar_section("b")

    host.notification_manager.show.assert_called_once()
    kwargs = host.notification_manager.show.call_args.kwargs
    actions = dict(kwargs.get("actions", []))
    assert "Undo" in actions
    assert "Favorites" not in kwargs.get("message", "")  # sanity: not a copy-paste toast
    assert "B" in kwargs.get("message", "")  # section title (SimpleNamespace title="B")


def test_undo_restores_at_order_correct_position(tmp_path):
    """order=[a,b,c]; hide b; Undo -> [a,b,c], never [a,c,b]."""
    host = _make_host(tmp_path, ["a", "b", "c"])

    host._hide_sidebar_section("b")
    assert host.config.sidebar_visible_sections == ["a", "c"]

    kwargs = host.notification_manager.show.call_args.kwargs
    undo = dict(kwargs["actions"])["Undo"]
    undo()

    assert host.config.sidebar_visible_sections == ["a", "b", "c"]
    assert host._apply_sidebar_visibility.call_count == 2  # hide, then undo


def test_hide_is_a_noop_when_already_hidden(tmp_path):
    host = _make_host(tmp_path, ["a", "b", "c"])
    host.config.sidebar_visible_sections = ["a", "c"]  # b already hidden

    host._hide_sidebar_section("b")

    assert host.config.sidebar_visible_sections == ["a", "c"]
    host._apply_sidebar_visibility.assert_not_called()
    host.notification_manager.show.assert_not_called()
