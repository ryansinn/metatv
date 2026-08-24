"""One line of removable chips, standing where a 250px column used to.

The chips are drawn here; *which* chips is decided in ``filter_chips.py``,
which has no Qt in it. This file is layout and wiring only.

Two things it does that are not obvious:

**It never wraps.** The bar is one row, always the same height, so the result
list below it does not jump when a filter is added. Chips that do not fit are
hidden behind a ``+N`` marker that opens the panel — the same shape as the
sidebar's row budget, and for the same reason: a surface that reflows is a
surface you cannot glance at.

**It measures before it hides.** The budget is computed from ``sizeHint``
widths against the bar's actual width, so it is correct at any window size
rather than at the one it was written on.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QWidget,
)

from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.filter_chips import FilterChip

#: Bar height. Fixed so that adding or clearing a filter never moves the list.
BAR_HEIGHT = 32

#: Chip height. Comfortably over 2 x RADIUS_SM, so Qt honours the corner radius
#: instead of silently squaring it (see docs/V3_INTERFACE_SPEC.md, Q10).
CHIP_HEIGHT = 22


#: A plain QWidget does not paint its stylesheet background or border — it
#: leaves both to the parent unless WA_StyledBackground is set. The tokens are
#: correct without it and nothing raises; the chips simply render as bare text
#: on the page colour. No token or stylesheet test can see this, because
#: nothing about the STYLE is wrong. Looking at the render is what catches it.
_STYLED = Qt.WidgetAttribute.WA_StyledBackground

class _Chip(QWidget):
    """One constraint, with the × that lifts it."""

    removed = pyqtSignal(str)

    def __init__(self, chip: FilterChip, parent=None):
        super().__init__(parent)
        self._facet = chip.facet
        self.setFixedHeight(CHIP_HEIGHT)
        self.setToolTip(chip.tooltip)
        self.setAttribute(_STYLED, True)
        _theme.style(self, "FILTER_CHIP")

        row = QHBoxLayout(self)
        row.setContentsMargins(_theme.space_px(_theme.SPACE_SM), 0, 2, 0)
        row.setSpacing(_theme.space_px(_theme.SPACE_XS))

        self._label = QLabel(chip.label)
        _theme.style(self._label, "FILTER_CHIP_LABEL")
        row.addWidget(self._label)

        self._close = QPushButton(_icons.close_icon)
        self._close.setFixedSize(16, 16)
        _theme.style(self._close, "FILTER_CHIP_CLOSE")
        self._close.setToolTip(f"Remove this filter — {chip.label}")
        cursor_affordance.set_clickable(self._close)
        self._close.clicked.connect(lambda: self.removed.emit(self._facet))
        row.addWidget(self._close)

    def facet(self) -> str:
        return self._facet

    def label(self) -> str:
        return self._label.text()


class FilterChipBar(QWidget):
    """The active-filter line: chips, an overflow marker, and the way back in.

    Signals:
        remove_requested: A chip's × was clicked. Carries the chip's facet.
        add_requested:    "+ Add filter" (or the overflow marker) was clicked —
                          the host should reveal the full panel.
        clear_requested:  "Clear all" was clicked.
    """

    remove_requested = pyqtSignal(str)
    add_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filterChipBar")
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(_STYLED, True)
        _theme.style(self, "FILTER_CHIP_BAR")

        pad = _theme.space_px(_theme.SPACE_SM)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(pad, 0, pad, 0)
        self._row.setSpacing(_theme.space_px(_theme.SPACE_XS))
        # A QHBoxLayout normally publishes the sum of its children as the
        # widget's minimum width. That would make the bar un-shrinkable — and
        # since the bar spans the result list, it would make the WINDOW
        # un-shrinkable, a filter chip holding the whole app open. It would
        # also mean the bar never gets narrow enough to notice it is short of
        # room, so the overflow marker below could never fire.
        #
        # SetNoConstraint stops the layout writing that minimum, and the
        # explicit minimumWidth(0) overrides the hint. The bar then reports "I
        # can be any width", and decides for itself which chips fit.
        self._row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(0)

        self._chips: list[_Chip] = []
        self._model: list[FilterChip] = []

        # Empty state. Not "No filters" — that describes the control. This
        # describes the list, which is what the line is for.
        self._empty = QLabel("Showing everything")
        _theme.style(self._empty, "FILTER_CHIP_EMPTY")
        self._row.addWidget(self._empty)

        self._overflow = QPushButton("")
        self._overflow.setFixedHeight(CHIP_HEIGHT)
        _theme.style(self._overflow, "FILTER_CHIP_OVERFLOW")
        cursor_affordance.set_clickable(self._overflow)
        self._overflow.clicked.connect(self.add_requested.emit)
        self._overflow.hide()
        self._row.addWidget(self._overflow)

        self._add = QPushButton(f"{_icons.add_icon} Add filter")
        self._add.setFixedHeight(CHIP_HEIGHT)
        _theme.style(self._add, "FILTER_CHIP_ADD")
        self._add.setToolTip("Open the full filter panel")
        cursor_affordance.set_clickable(self._add)
        self._add.clicked.connect(self.add_requested.emit)
        self._row.addWidget(self._add)

        self._row.addStretch(1)

        self._clear = QPushButton("Clear all")
        self._clear.setFixedHeight(CHIP_HEIGHT)
        _theme.style(self._clear, "FILTER_CHIP_CLEAR")
        self._clear.setToolTip("Remove every active filter")
        cursor_affordance.set_clickable(self._clear)
        self._clear.clicked.connect(self.clear_requested.emit)
        self._clear.hide()
        self._row.addWidget(self._clear)

    # ── Content ──────────────────────────────────────────────────────────────

    def set_chips(self, chips: list[FilterChip]) -> None:
        """Replace the line's contents.

        Chips are rebuilt rather than diffed: there are at most a dozen, they
        carry no state worth preserving across a filter change, and a diff here
        would be more code than the thing it optimises.
        """
        for chip in self._chips:
            self._row.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []
        self._model = list(chips)

        for index, chip in enumerate(chips):
            widget = _Chip(chip, self)
            widget.removed.connect(self.remove_requested.emit)
            # Before the overflow marker, which is before "+ Add filter".
            self._row.insertWidget(index, widget)
            self._chips.append(widget)

        self._empty.setVisible(not chips)
        self._clear.setVisible(len(chips) >= 1)
        self._apply_budget()

    def chip_labels(self) -> list[str]:
        """The labels currently on the line, in order — for tests and probes."""
        return [c.label() for c in self._chips]

    def visible_chip_labels(self) -> list[str]:
        """Only the chips that actually fit."""
        return [c.label() for c in self._chips if c.isVisible()]

    # ── Budget ───────────────────────────────────────────────────────────────

    def resizeEvent(self, event):  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._apply_budget()

    def _apply_budget(self) -> None:
        """Hide the chips that do not fit, and say how many that was.

        Runs against the bar's real width, so the answer is right at any window
        size. With no width yet (before first layout) every chip stays visible:
        an unmeasured bar must not decide it has no room.
        """
        available = self.width()
        if available <= 0 or not self._chips:
            self._overflow.hide()
            return

        pad = _theme.space_px(_theme.SPACE_SM)
        gap = _theme.space_px(_theme.SPACE_XS)
        fixed = pad * 2 + self._add.sizeHint().width() + gap
        if self._clear.isVisible():
            fixed += self._clear.sizeHint().width() + gap
        budget = available - fixed

        widths = [c.sizeHint().width() for c in self._chips]
        # Reserve room for the marker up front when everything cannot fit —
        # otherwise the last chip takes the space the marker then needs, and the
        # marker is what makes the hidden ones reachable.
        total = sum(widths) + gap * (len(widths) - 1)
        reserve = 0 if total <= budget else self._overflow_width(len(self._chips))

        used = 0
        shown = 0
        for chip, width in zip(self._chips, widths):
            step = width + (gap if shown else 0)
            if used + step + reserve <= budget:
                chip.show()
                used += step
                shown += 1
            else:
                chip.hide()

        hidden = len(self._chips) - shown
        if hidden > 0:
            self._overflow.setText(f"+{hidden}")
            self._overflow.setToolTip(
                f"{hidden} more active filter{'s' if hidden != 1 else ''} "
                f"— open the panel to see them"
            )
            self._overflow.show()
        else:
            self._overflow.hide()

    def _overflow_width(self, count: int) -> int:
        """Width the ``+N`` marker will need, measured rather than guessed."""
        previous = self._overflow.text()
        self._overflow.setText(f"+{count}")
        width = self._overflow.sizeHint().width() + _theme.space_px(_theme.SPACE_XS)
        self._overflow.setText(previous)
        return width
