"""App-wide pointing-hand cursor affordance — one install point, no per-widget edits.

MetaTV is a native Qt app, so clickable controls don't get the web-style "hand"
cursor on hover by default. We adopt the hand as a clickability affordance via a
*single* application-level event filter installed once at startup
(:func:`install`). On every widget ``Enter`` event the filter decides whether the
hovered widget is clickable and, if so, gives it
``Qt.CursorShape.PointingHandCursor``. There is exactly one chokepoint — adding
the affordance to a new surface never requires touching that surface.

What counts as clickable
------------------------
* Any :class:`~PyQt6.QtWidgets.QAbstractButton` (covers ``QPushButton`` — i.e.
  the filter chips and the rail/action buttons), **except** ``QCheckBox`` and
  ``QRadioButton`` (their box/circle is the affordance, a hand would mislead).
* Any widget that opts in with the dynamic property ``clickable=True``. Custom
  clickable ``QLabel``/``QWidget``s (poster, chips, collapse carets, clickable
  rows) opt in with :func:`set_clickable` at their own construction site — no
  change here is needed to support them.

Always excluded: disabled widgets (``isEnabled() == False``) — a disabled
control offers nothing to click, so it keeps the default cursor.

Adding a new clickable widget
------------------------------
A plain ``QPushButton``/``QToolButton`` (any ``QAbstractButton``) needs nothing
— it qualifies automatically. Every other hand-rolled clickable (a ``QLabel``
with a ``mousePressEvent`` override, a clickable row ``QWidget``, a caret) must
call :func:`set_clickable` once at construction (and again on any state change
that flips its clickability, e.g. a poster that only becomes clickable once an
image loads). Never call ``setCursor(Qt.CursorShape.PointingHandCursor)``
directly — that hand-rolls a parallel path around this chokepoint and won't
pick up the disabled-widget handling above. Checkboxes and radio buttons are
excluded by convention (the box/circle is already the affordance) — don't
route them through :func:`set_clickable`.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QRadioButton,
    QWidget,
)
from loguru import logger

#: QAbstractButton subclasses whose own widget *is* the affordance — never get
#: the hand even though they are buttons.
_EXCLUDED_BUTTON_TYPES: tuple[type, ...] = (QCheckBox, QRadioButton)

#: Dynamic property a custom (non-button) widget can set to opt into the hand.
CLICKABLE_PROPERTY = "clickable"


def _is_clickable(widget: QWidget) -> bool:
    """Return True if *widget* should show the pointing-hand cursor on hover.

    A widget is clickable when it is a (non-checkbox/radio) button, or it has
    opted in via the ``clickable=True`` dynamic property.
    """
    if isinstance(widget, _EXCLUDED_BUTTON_TYPES):
        return False
    if isinstance(widget, QAbstractButton):
        return True
    return bool(widget.property(CLICKABLE_PROPERTY))


class PointingHandFilter(QObject):
    """Application-level event filter that applies the hand cursor on hover.

    Installed once on the :class:`QApplication`; it receives ``Enter`` events for
    every widget and sets/clears the pointing-hand cursor accordingly. The filter
    never consumes the event (always returns ``False``) so normal hover handling
    is untouched.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.Enter and isinstance(obj, QWidget):
            if _is_clickable(obj):
                if obj.isEnabled():
                    obj.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    # A control that was enabled when first hovered (cursor set)
                    # may later be disabled; clear so it doesn't keep the hand.
                    obj.unsetCursor()
        return False  # never swallow the event


def set_clickable(widget: QWidget, clickable: bool = True) -> None:
    """Opt a non-button widget into (or out of) the pointing-hand affordance.

    Sets the ``clickable`` dynamic property the installed filter checks on
    hover (see :data:`CLICKABLE_PROPERTY`). Because the filter only reacts to
    ``Enter`` events, this also applies or clears the cursor immediately, so a
    widget whose clickability changes while the pointer is already over it
    (e.g. a poster becoming clickable the instant its image finishes loading)
    updates without waiting for the next hover.

    This is the one call every hand-rolled clickable widget (a custom
    ``QLabel``/``QWidget`` with its own ``mousePressEvent`` or ``clicked``
    signal) should use instead of a direct
    ``setCursor(Qt.CursorShape.PointingHandCursor)`` — buttons never need it,
    they qualify for free via :func:`_is_clickable`.

    Args:
        widget: The widget to mark clickable (or not).
        clickable: Whether *widget* is currently clickable. Defaults to
            ``True`` for the common "always clickable" case; pass a live
            boolean for widgets whose clickability toggles at runtime.
    """
    widget.setProperty(CLICKABLE_PROPERTY, clickable)
    if clickable and widget.isEnabled():
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
    else:
        widget.unsetCursor()


def install(app: QApplication) -> PointingHandFilter:
    """Install the pointing-hand affordance filter on *app* (call once at startup).

    Args:
        app: The running ``QApplication`` instance.

    Returns:
        The installed :class:`PointingHandFilter`. The caller should keep a
        reference (e.g. on the app) so it is not garbage-collected.
    """
    filt = PointingHandFilter(app)
    app.installEventFilter(filt)
    logger.debug("Pointing-hand cursor affordance installed on QApplication")
    return filt
