"""Responsive flow layout — wraps items like CSS flex-wrap.

Items define their own minimumSizeHint; the layout packs them left-to-right
and wraps to the next row when there is no more horizontal space.  Column
count adjusts automatically on every resize — no manual reflow needed.

Usage:
    layout = FlowLayout(parent_widget, spacing=8)
    layout.addWidget(card1)
    layout.addWidget(card2)
    # Cards reflow automatically when the parent is resized.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QWidget, QWidgetItem


def enable_height_for_width(widget: "QWidget | None") -> None:
    """Opt *widget*'s size policy into height-for-width so a wrapping flow layout
    actually wraps when the widget is nested in a box layout.

    A ``QBoxLayout`` only queries a child's ``heightForWidth`` (the value a flow
    layout uses to grow taller and wrap to more rows) when the child's size policy
    has the flag enabled — merely returning ``hasHeightForWidth() == True`` from the
    layout is not enough.  Without this, a nested flow container lays its items out
    in a single row that clips at the parent's right edge instead of wrapping.

    Called from every flow-layout constructor so nested chip rows wrap for free; a
    no-op (and harmless) for containers that are a ``QScrollArea``'s direct widget.
    """
    if widget is None:
        return
    sp = widget.sizePolicy()
    sp.setHeightForWidth(True)
    widget.setSizePolicy(sp)


class FlowLayout(QLayout):
    """A layout that flows items left-to-right, wrapping to the next row."""

    def __init__(self, parent=None, spacing: int = 8, *,
                 h_spacing: "int | None" = None,
                 v_spacing: "int | None" = None) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        # A chip row usually wants tighter rows than columns, so the two are
        # separable; `spacing` sets both unless one is named explicitly.
        self._h_spacing = spacing if h_spacing is None else h_spacing
        self._v_spacing = spacing if v_spacing is None else v_spacing
        self.setSpacing(self._h_spacing)
        enable_height_for_width(parent)

    # ── QLayout interface ──────────────────────────────────────────────

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    # ── Layout engine ──────────────────────────────────────────────────

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            widget = item.widget()
            # isHidden() (explicit hide only) rather than `not isVisible()`
            # (ancestor-gated). When the parent container is COLLAPSED the chips
            # are not explicitly hidden, so isVisible() wrongly returns False,
            # every item is skipped, heightForWidth returns 0, and the row
            # renders with zero height after expansion. The same is true under a
            # headless test runner, where nothing is ever shown.
            #
            # This layout used to lay out hidden items unconditionally — the
            # "leaves a hole" behaviour, one of the three visibility policies the
            # componentization audit found across four copies of this class.
            if widget is not None and widget.isHidden():
                continue

            hint = item.sizeHint()
            w, h = hint.width(), hint.height()

            # Wrap to next row if item doesn't fit
            if x + w > effective.right() and x > effective.x():
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0

            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x += w + self._h_spacing
            row_height = max(row_height, h)

        return y + row_height - rect.y() + margins.bottom()


def _default_flow_visible(widget: "QWidget") -> bool:
    """Whether *widget* takes part in a flow.

    ``isHidden()`` rather than ``not isVisible()``, and the difference decides
    whether a chip row has a hole in it. ``isVisible()`` is False for a widget
    whose window has not been shown yet — which is EVERY widget under a headless
    test runner, and any widget built before its parent is shown. Skipping those
    lays every chip at the origin; laying out an explicitly ``hide()``-ed one
    leaves a gap where it sits. ``isHidden()`` asks the question actually meant:
    did someone hide this on purpose?

    A widget may override the answer with a ``flow_visible`` attribute — the tag
    cloud's buttons carry their own filtered/unfiltered state, which is not the
    same question as Qt visibility.
    """
    override = getattr(widget, "flow_visible", None)
    if override is not None:
        return bool(override)
    return not widget.isHidden()


class FlowContainer:
    """A manually-driven flow of widgets that reports the height it used.

    The sibling of :class:`FlowLayout`, and NOT a duplicate of it — the contract
    differs. ``FlowLayout`` is a ``QLayout``: Qt decides when to lay out, and the
    host never asks how tall the result is. ``FlowContainer`` is driven by the
    host, which calls :meth:`relayout` with a width and needs the height BACK to
    size a scroll area or a section. Two real needs; one implementation each,
    both here rather than copied per caller.

    This replaces two acknowledged copies. ``weighted_tag_cloud._FlowLayout``
    said so itself: *"the same layout primitive used by
    ``discover_card._FlowLayout`` … We define our own copy here rather than
    importing the private class from ``discover_card`` so this widget has no
    coupling to the Discover subsystem."* Avoiding that coupling was right; the
    copy was the wrong way to get it, and a shared module is the right one.

    Args:
        container: The parent widget items are positioned within.
        spacing: Horizontal spacing, and the default for vertical.
        v_spacing: Vertical spacing when rows should be tighter than columns.
        is_visible: Predicate deciding which items are placed. Defaults to
            :func:`_default_flow_visible`.
    """

    def __init__(self, container: "QWidget", spacing: int = 8,
                 v_spacing: "int | None" = None,
                 is_visible=None) -> None:
        self._container = container
        self._items: "list[QWidget]" = []
        self._h_spacing = spacing
        self._v_spacing = spacing if v_spacing is None else v_spacing
        self._is_visible = is_visible or _default_flow_visible
        enable_height_for_width(container)

    def add(self, widget: "QWidget") -> None:
        """Reparent *widget* into the container and place it in the flow."""
        widget.setParent(self._container)
        self._items.append(widget)

    def relayout(self, available_width: int) -> int:
        """Position every visible item within *available_width*.

        Returns:
            The total height used — 0 when nothing is placed, so a caller can
            collapse an empty section rather than reserving a blank row.
        """
        x = y = row_h = 0
        placed = False
        for widget in self._items:
            if not self._is_visible(widget):
                continue
            hint = widget.sizeHint()
            w, h = hint.width(), hint.height()
            if x + w > available_width and x > 0:
                x = 0
                y += row_h + self._v_spacing
                row_h = 0
            widget.setGeometry(QRect(x, y, w, h))
            x += w + self._h_spacing
            row_h = max(row_h, h)
            placed = True
        return y + row_h if placed else 0

    def clear(self) -> None:
        """Drop every item, scheduling each for deletion."""
        for widget in self._items:
            widget.deleteLater()
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
