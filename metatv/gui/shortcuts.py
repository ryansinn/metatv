"""KEYS-1 — every keyboard shortcut in ONE table, installed once on the window.

Before this the app had exactly one accelerator (``Ctrl+,`` on the Settings
``QAction``), and the roadmap line asking for the rest carried its own design
constraints. Those constraints are why this is a registry rather than a
sprinkling of ``QShortcut``s:

* **Window-owned ``QAction``s, never ``QShortcut``s.** A ``QShortcut`` parented
  to whichever widget happened to be handy is invisible — it cannot appear in a
  menu, so the only way to learn it is to be told. Every row here becomes a
  ``QAction`` the window owns, and (bar one deliberate exception, ``Esc``) each
  one is placed in a menu, where it advertises its own key.
* **One table, read three ways.** The same rows build the actions, annotate the
  tooltips of the controls they drive, and fill the cheat-sheet dialog. A
  second list would be a second answer to "what are the shortcuts", and the
  cheat-sheet is the one surface where being wrong is worse than being absent.
* **The ``Ctrl+1..5`` order is DERIVED, not typed.** The five view rows are
  built from ``app_header.NAV_CHIP_SPECS`` — the tuple that lays the switcher
  out left to right — mapped through ``main_window_nav._NAV_VIEW_TARGETS`` to
  the ``view:<name>`` deep link each chip stands for. A hand-written list here
  would silently disagree with the chips the first time one moved, which is
  precisely the failure the chip specs were made module-level to stop.

The text-field constraint
-------------------------
None of these may fire while the user is typing, except ``Esc`` and the
focus-search binding. Two halves:

* Modified bindings (``Ctrl+…``) are unambiguous — nothing types them — so
  they stay live everywhere.
* The three bindings that are ordinary characters (``/``, ``?``, ``Space``)
  are swallowed by :class:`_TextFieldShortcutGuard` while a text field inside
  this window has focus. It answers the ``ShortcutOverride`` event, which is
  Qt's own "should this key be a shortcut or a keystroke?" question, and it is
  installed on the **application** rather than the window because that is the
  only place a filter runs BEFORE the focus widget's own handling — an
  editable ``QLineEdit`` accepts the override itself for printable keys, so a
  window-level filter would never see the event it is there to answer. The
  object is parented to the window and dies with it.

``Esc`` is forwarded, never re-implemented: the focused text box and the
overlays (preview lightbox, poster lightbox, Explore trail-map) each already
own what Escape means to them, and the shortcut fires ahead of their
``keyPressEvent``. So the handler re-sends the key to whichever of them is in
front, and their single definition of "close" stays the only one.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QAction, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.dialog_chrome import dialog_buttons

#: Widget types that mean "the user is typing". The single-key bindings are
#: swallowed while one of these has focus; ``Esc`` is forwarded into it.
TEXT_ENTRY_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit)

#: Modifiers that make a binding un-typeable, so it stays live in a text field.
_HARD_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)


@dataclass(frozen=True)
class Shortcut:
    """One row of the registry — the whole definition of one accelerator.

    Attributes:
        id: Stable identifier, used as the key of :func:`install`'s result and
            as the object name of the cheat-sheet's labels.
        label: What it does — the cheat-sheet's right column, and the menu
            entry's text unless ``menu_text`` overrides it.
        section: Cheat-sheet grouping heading.
        handler: Name of the method on the window that performs it. A NAME, not
            a bound callable, so the table can be read (and guarded) without a
            live window — same reason ``NAV_CHIP_SPECS`` names its slots.
        keys: Portable key strings (``"Ctrl+1"``, ``"/"``). ``Ctrl`` renders and
            matches as ``Cmd`` on macOS; ``QKeySequence`` does that mapping.
        alias_keys: Sequences that must also FIRE the row but are not worth
            advertising — the same key reached another way. ``?`` needs one:
            a US keyboard sends ``Shift+?``, and a shortcut registered as the
            bare ``?`` does not match it (measured, not assumed), while a
            cheat-sheet reading "? or Shift+? " is noise.
        standard: A platform-defined binding used INSTEAD of typing the keys out
            (``StandardKey.Find`` is ``Ctrl+F`` / ``⌘F``). Its bindings come
            first, then ``keys``.
        arg: A single argument handed to the handler, or ``None`` to call it
            bare. Only the view rows use it (``navigate_to("view:epg")``).
        menu: Window attribute holding the ``QMenu`` this action is added to,
            or ``None`` for an action the window owns without a menu entry.
        existing_action: Window attribute of a ``QAction`` that ALREADY exists
            and already does this job — the shortcut is attached to it rather
            than a second action being built beside it.
        menu_text: The menu entry's own text, when it wants an icon and the
            trailing ellipsis a dialog-opening entry owes the user.
        tooltip_host: Window attribute of the control (or action) that EXISTS
            already and whose tooltip gains the key text, per the ``Ctrl+,``
            precedent on the sidebar Settings button. An action ``install``
            builds itself is tooltipped there and needs no entry here.
        text_keys: The subset of ``keys`` that is an ordinary character, and so
            must be swallowed while a text field has focus.
    """

    id: str
    label: str
    section: str
    handler: str
    keys: tuple[str, ...] = ()
    alias_keys: tuple[str, ...] = ()
    standard: QKeySequence.StandardKey | None = None
    arg: str | None = None
    menu: str | None = None
    menu_text: str | None = None
    existing_action: str | None = None
    tooltip_host: str | None = None
    text_keys: tuple[str, ...] = ()

    def sequences(self) -> list[QKeySequence]:
        """Every key sequence that FIRES this row, platform-resolved."""
        seqs: list[QKeySequence] = []
        if self.standard is not None:
            seqs.extend(QKeySequence.keyBindings(self.standard))
        seqs.extend(QKeySequence(k) for k in self.keys)
        seqs.extend(QKeySequence(k) for k in self.alias_keys)
        return seqs

    def display_sequences(self) -> list[QKeySequence]:
        """The sequences worth SHOWING — not always the ones that fire.

        A standard key can carry more than one binding: X11 reports Find as
        both ``Ctrl+F`` and the dedicated Find media key, and a tooltip reading
        "Ctrl+F or Find or /" is worse than useless. All of them stay bound;
        only the first is advertised.
        """
        seqs: list[QKeySequence] = []
        if self.standard is not None:
            bindings = QKeySequence.keyBindings(self.standard)
            if bindings:
                seqs.append(bindings[0])
        seqs.extend(QKeySequence(k) for k in self.keys)
        return seqs

    def key_text(self) -> str:
        """The keys as the user's own platform writes them ("Ctrl+F or /")."""
        return " or ".join(
            seq.toString(QKeySequence.SequenceFormat.NativeText)
            for seq in self.display_sequences()
        )


#: ``switch_to_list_view`` owns the Search chip itself (``_NAV_VIEW_TARGETS``
#: records its chip as ``None`` for that reason), so the one chip that cannot be
#: resolved by inverting that table is named here rather than guessed.
_SEARCH_CHIP_VIEW = "list"


def _view_shortcuts() -> tuple[Shortcut, ...]:
    """``Ctrl+1..5``, built FROM the switcher so the two can never disagree.

    Returns:
        One row per nav chip, in the chips' left-to-right order.
    """
    from metatv.gui.app_header import NAV_CHIP_SPECS
    from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS

    by_chip = {
        chip: name for name, (_method, chip) in _NAV_VIEW_TARGETS.items() if chip
    }
    rows: list[Shortcut] = []
    for position, (attr, label, *_rest) in enumerate(NAV_CHIP_SPECS, start=1):
        view = by_chip.get(attr)
        if view is None and attr == "search_chip":
            view = _SEARCH_CHIP_VIEW
        if view is None:
            logger.warning(
                "shortcuts: nav chip {} has no view: target — no Ctrl+{} for it",
                attr, position,
            )
            continue
        rows.append(Shortcut(
            id=f"view_{position}",
            label=label,
            section="Views",
            handler="navigate_to",
            arg=f"view:{view}",
            keys=(f"Ctrl+{position}",),
            menu="_view_menu",
            tooltip_host=attr,
        ))
    return tuple(rows)


#: THE table. Everything keyboard-driven in the app is a row here.
SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut(
        id="focus_search",
        label="Focus search",
        section="Navigation",
        handler="_shortcut_focus_search",
        keys=("/",),
        # StandardKey rather than a typed "Ctrl+F": it is ⌘F on macOS and
        # Ctrl+F elsewhere, and Qt is the authority on which.
        standard=QKeySequence.StandardKey.Find,
        menu="_view_menu",
        tooltip_host="search_input",
        text_keys=("/",),
    ),
    Shortcut(
        id="escape",
        label="Clear the search box, or close the overlay in front",
        section="Navigation",
        handler="_shortcut_escape",
        keys=("Esc",),
        # The ONE row with no menu entry, deliberately: what Escape does depends
        # entirely on what is in front of you, so a menu item promising one of
        # its three behaviours would be wrong two-thirds of the time. It is in
        # the cheat-sheet, which can say all three.
        menu=None,
    ),
    # The views sit between Navigation and Playback because the cheat-sheet
    # renders the table in order, section by section — a row filed under a
    # section that has already been drawn would jump up the page.
    *_view_shortcuts(),
    Shortcut(
        id="play_pause",
        label="Play / pause",
        section="Playback",
        handler="_shortcut_play_pause",
        keys=("Space",),
        menu="_playback_menu",
        text_keys=("Space",),
    ),
    Shortcut(
        id="stop",
        label="Stop playback",
        section="Playback",
        handler="_shortcut_stop",
        keys=("Ctrl+.",),
        menu="_playback_menu",
    ),
    Shortcut(
        id="next_channel",
        label="Select the next channel",
        section="Playback",
        handler="_shortcut_next_channel",
        keys=("Ctrl+Down",),
        menu="_playback_menu",
    ),
    Shortcut(
        id="prev_channel",
        label="Select the previous channel",
        section="Playback",
        handler="_shortcut_prev_channel",
        keys=("Ctrl+Up",),
        menu="_playback_menu",
    ),
    Shortcut(
        id="toggle_sidebar",
        label="Show or hide the sidebar",
        section="Panels",
        handler="_toggle_sidebar_from_menu",
        keys=("Ctrl+B",),
        existing_action="_sidebar_visible_action",
        tooltip_host="_sidebar_visible_action",
    ),
    Shortcut(
        id="toggle_details",
        label="Show or hide the details pane",
        section="Panels",
        handler="_toggle_details_from_menu",
        keys=("Ctrl+D",),
        existing_action="_details_visible_action",
        tooltip_host="_details_visible_action",
    ),
    Shortcut(
        id="cheat_sheet",
        label="Keyboard shortcuts",
        section="Help",
        handler="show_keyboard_shortcuts",
        keys=("?", "F1"),
        alias_keys=("Shift+?",),
        menu="_tools_menu",
        menu_text=f"{_icons.keyboard_icon}  Keyboard Shortcuts…",
        # F1 is a function key — nothing types it, so it stays live in a text
        # field and is the way to reach this from inside the search box.
        text_keys=("?",),
    ),
)


def guarded_key_codes() -> frozenset[int]:
    """The ``Qt.Key`` codes swallowed while a text field has focus."""
    codes: set[int] = set()
    for spec in SHORTCUTS:
        for key in spec.text_keys:
            seq = QKeySequence(key)
            if seq.count() != 1:
                logger.warning("shortcuts: {} is not a single keystroke", key)
                continue
            codes.add(seq[0].key())
    return frozenset(codes)


def is_text_entry(widget: QWidget | None) -> bool:
    """True when *widget* is somewhere the user types."""
    return isinstance(widget, TEXT_ENTRY_TYPES)


def send_escape(widget: QWidget) -> None:
    """Hand *widget* an Escape key press as if the user had pressed it there.

    The shortcut map runs ahead of ``keyPressEvent``, so a window-owned ``Esc``
    action takes the key away from the box or overlay that already knows what
    Escape means there. Re-sending it gives the key back rather than growing a
    second definition of "close" beside each existing one.

    The action is switched OFF for the length of the send, which is not
    belt-and-braces: ``QApplication::notify`` runs the shortcut map on every
    key press it delivers, synthetic ones included, so the forwarded Escape
    re-matches this very action — the key is consumed by the shortcut and the
    widget never sees it, and the handler calls itself until the stack runs
    out. Measured, not theorised: that is what the first run did.
    """
    window = widget.window()
    action = None
    if window is not None:
        action = (window.__dict__.get("_shortcut_actions") or {}).get("escape")
    if action is not None:
        action.setEnabled(False)
    try:
        QApplication.sendEvent(
            widget,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Escape,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
    finally:
        if action is not None:
            action.setEnabled(True)


class _TextFieldShortcutGuard(QObject):
    """Answers ``ShortcutOverride`` so ``/``, ``?`` and ``Space`` can be typed.

    Installed on the QApplication (see the module docstring) but owned by the
    window, and scoped to it: only a text field inside *window* suppresses the
    binding, so another window's typing is nobody's business here.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._keys = guarded_key_codes()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def blocks(self, event: QKeyEvent) -> bool:
        """True when this keystroke must reach the text field, not a shortcut."""
        if event.key() not in self._keys:
            return False
        if event.modifiers() & _HARD_MODIFIERS:
            return False
        focused = QApplication.focusWidget()
        if not is_text_entry(focused):
            return False
        return focused is self._window or self._window.isAncestorOf(focused)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.ShortcutOverride and self.blocks(event):
            # Accepting the override is Qt's own "treat this as a keystroke"
            # answer — the character lands in the box and no shortcut fires.
            event.accept()
            return True
        return False


def install(window) -> dict[str, QAction]:
    """Build every shortcut on *window* and return the actions by row id.

    Called at the end of ``create_menu_bar``, when every menu the table names
    exists. Actions are ``WindowShortcut``-scoped, so they fire anywhere in the
    window and nowhere outside it — a dialog's own Escape and Enter keep
    working because a dialog is a different window.

    Args:
        window: The ``MainWindow``. Every ``handler`` in the table must resolve
            on it; one that does not is logged and skipped rather than crashing
            the menu bar.

    Returns:
        ``{shortcut id: QAction}`` — also stashed on the window as
        ``_shortcut_actions`` for the cheat-sheet and the tests.
    """
    actions: dict[str, QAction] = {}
    separated: set[str] = set()

    for spec in SHORTCUTS:
        action = _resolve_action(window, spec, separated)
        if action is None:
            continue
        action.setShortcuts(spec.sequences())
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if spec.existing_action is None:
            # An action built here has no prior tooltip to append to, so it
            # gets the whole thing; the ones that already existed are handled
            # by annotate_tooltips, which keeps what they say.
            action.setToolTip(f"{spec.label} ({spec.key_text()})")
        actions[spec.id] = action

    window._shortcut_actions = actions
    window._shortcut_key_guard = _TextFieldShortcutGuard(window)
    return actions


def _resolve_action(window, spec: Shortcut, separated: set[str]) -> QAction | None:
    """The ``QAction`` for *spec* — the existing one, or a new one in its menu."""
    if spec.existing_action is not None:
        action = window.__dict__.get(spec.existing_action)
        if action is None:
            logger.warning(
                "shortcuts: {} names a missing action {}",
                spec.id, spec.existing_action,
            )
        return action

    handler = getattr(window, spec.handler, None)
    if handler is None:
        logger.warning("shortcuts: {} names a missing handler {}", spec.id, spec.handler)
        return None

    action = QAction(spec.menu_text or spec.label, window)
    if spec.arg is None:
        action.triggered.connect(lambda _checked=False, fn=handler: fn())
    else:
        action.triggered.connect(
            lambda _checked=False, fn=handler, arg=spec.arg: fn(arg)
        )

    if spec.menu is None:
        # No menu, so nothing else would give the window the action — and
        # without that its shortcut never reaches the shortcut map.
        window.addAction(action)
        return action

    menu = window.__dict__.get(spec.menu)
    if menu is None:
        logger.warning("shortcuts: {} names a missing menu {}", spec.id, spec.menu)
        window.addAction(action)
        return action
    if spec.menu not in separated and not menu.isEmpty():
        menu.addSeparator()
    separated.add(spec.menu)
    menu.addAction(action)
    return action


def annotate_tooltips(window) -> None:
    """Append each shortcut's keys to its control's EXISTING tooltip.

    Called at the end of ``_create_header``, once the chips and the search box
    exist — the menu actions were built earlier and are already there. The
    format follows the sidebar Settings button's long-standing "Open
    application settings (Ctrl+,)".

    Idempotent: a tooltip that already names the keys is left alone, so a
    second call (or a re-themed rebuild) cannot stack them up.
    """
    for spec in SHORTCUTS:
        if spec.tooltip_host is None:
            continue
        host = window.__dict__.get(spec.tooltip_host)
        if host is None:
            logger.warning(
                "shortcuts: {} names a missing tooltip host {}",
                spec.id, spec.tooltip_host,
            )
            continue
        keys = spec.key_text()
        existing = host.toolTip()
        if keys in existing:
            continue
        host.setToolTip(f"{existing} ({keys})" if existing else f"{spec.label} ({keys})")


class ShortcutCheatSheetDialog(QDialog):
    """The whole table, on screen — an accelerator nobody can find is not one.

    Read straight off :data:`SHORTCUTS`, so it cannot describe a key the app
    does not have (or miss one it does).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel(f"{_icons.keyboard_icon}  Keyboard Shortcuts")
        _theme.style(title, "DIALOG_TITLE")
        root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        # The keys column hugs its content; the description takes the slack, so
        # the two read as two columns rather than one ragged run of text.
        grid.setColumnStretch(1, 1)

        #: ``{shortcut id: (keys label, action label)}`` — what the layout test
        #: measures, and what a caller would read the sheet back from.
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        line = 0
        for section in dict.fromkeys(spec.section for spec in SHORTCUTS):
            heading = QLabel(section)
            _theme.style(heading, "DIALOG_SUBHEADER")
            grid.addWidget(heading, line, 0, 1, 2)
            line += 1
            for spec in (s for s in SHORTCUTS if s.section == section):
                keys = QLabel(spec.key_text())
                keys.setObjectName(f"keys_{spec.id}")
                _theme.style(keys, "FIELD_LABEL")
                grid.addWidget(keys, line, 0)

                what = QLabel(spec.label)
                what.setObjectName(f"action_{spec.id}")
                what.setWordWrap(True)
                _theme.style(what, "SECTION_ITEM")
                grid.addWidget(what, line, 1)

                self.rows[spec.id] = (keys, what)
                line += 1

        root.addLayout(grid)
        root.addWidget(dialog_buttons(self, ok="Close", cancel=False))
