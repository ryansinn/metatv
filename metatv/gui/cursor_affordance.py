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
  clickable ``QLabel``s (poster, cast/genre links, collapse carets) can opt in
  later with a single ``label.setProperty("clickable", True)`` at their own
  construction site — no change here is needed to support them.

Always excluded: disabled widgets (``isEnabled() == False``) — a disabled
control offers nothing to click, so it keeps the default cursor.
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
