"""Channel-list QListView with a middle-click signal.

The only behavioural addition over a plain ``QListView`` is ``middle_clicked`` —
emitted with the row's ``QModelIndex`` on a middle mouse-button press over a valid
item.  MainWindow wires this to play the OPPOSITE of the bare double-click default
(resume vs. start-from-beginning), so the two mouse gestures cover both actions
without a context menu.

The view is also the Qt-geometry half of the poster-thumbnail hydration feature
(see ``channel_list_thumbnails.py`` for the "why" and the debounced request
logic). ``set_thumbnail_hydrator`` attaches a ``ChannelThumbnailHydrator``; the
view turns scroll, resize, and model reset/insert into a ``(first_row,
last_row)`` visible range via ``indexAt`` and forwards it to the hydrator —
the only Qt-viewport-pixel-dependent part of the feature, kept here rather than
in the hydrator so the hydrator's request/dedupe/repaint logic stays testable
without a real, shown, resized widget.
"""
from typing import Optional

from PyQt6.QtCore import QEvent, Qt, QModelIndex, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import QListView, QToolTip

from metatv.gui import cursor_affordance
from metatv.gui.channel_list_thumbnails import ChannelThumbnailHydrator


class ChannelListView(QListView):
    """``QListView`` that emits ``middle_clicked(index)`` on a middle-button press."""

    middle_clicked = pyqtSignal(QModelIndex)
    #: (section key, word_only) — a click on one half of a header's Whole|Part
    #: control. Narrowing is a DISPLAY choice over rows already fetched, so the
    #: host answers it on the model rather than re-running the query.
    section_mode_toggled = pyqtSignal(str, bool)
    #: A row chip was clicked: ``(facet, value)`` — e.g. ``("quality", "4K")``.
    #: MainWindow turns this into the same strict context filter a details-pane
    #: metadata click produces (docs/CONTEXT_FILTER_CHIPS.md).
    chip_clicked = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumbnail_hydrator: Optional[ChannelThumbnailHydrator] = None
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(self._request_hydration)
        # Chips are painted by the delegate, not child widgets, so hover has to
        # be tracked manually — without this, mouseMoveEvent only fires while a
        # button is held and the cursor never changes (#24).
        self.setMouseTracking(True)

    # ── Delegate-painted chip interaction (#24) ──────────────────────────────

    def _cell_at(self, pos: QPoint):
        """Return the ``_Cell`` painted under *pos*, or None.

        Asks the delegate for the rectangles it actually drew for that row, so
        the clickable area can never drift from the visible chip.
        """
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        delegate = self.itemDelegate()
        hit_cells = getattr(delegate, "hit_cells", None)
        if hit_cells is None:
            return None
        for rect, cell in hit_cells(index.row()):
            if rect.contains(pos):
                return cell
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        cell = self._cell_at(pos)
        # Pointing hand ONLY over something that actually does something: a
        # segment/chip that filters, or the action affordance. A cell that just
        # explains itself (the ×N variant badge) keeps the default cursor —
        # promising a click that does nothing is worse than no affordance.
        if (cell is not None and cell.facet) or self._action_hit(pos):
            cursor_affordance.set_clickable(self)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def viewportEvent(self, event) -> bool:
        """Render per-chip tooltips.

        A delegate-painted chip is not a widget, so ``setToolTip`` cannot reach
        it — the tooltip has to be produced on demand for whatever is under the
        cursor.
        """
        if event.type() == QEvent.Type.ToolTip:
            cell = self._cell_at(event.pos())
            if cell is not None and cell.tip:
                QToolTip.showText(event.globalPos(), cell.tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def _mode_toggle_hit(self, pos: QPoint):
        """``(section, word_only)`` when *pos* lands on an All|Word half.

        Asked of the delegate for the same reason ``_action_hit`` does it:
        the rect is recomputed, never stashed during paint, so the first click
        on a freshly scrolled header works.
        """
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        rects = getattr(self.itemDelegate(), "mode_toggle_rects", None)
        if rects is None:
            return None
        from metatv.gui.channel_list_roles import SECTION_TYPE_ROLE
        all_seg, word_seg = rects(self.visualRect(index), index, self.font())
        if word_seg.contains(pos):
            return index.data(SECTION_TYPE_ROLE), True    # Word — narrow it
        if all_seg.contains(pos):
            return index.data(SECTION_TYPE_ROLE), False   # All — open it up
        return None

    def _action_hit(self, pos: QPoint) -> bool:
        """Whether *pos* lands on a row's reserved action affordance (``⋯``).

        Asks the delegate to recompute the rect rather than reading one stashed
        during paint: the gutter is RESERVED on every row but only PAINTED on
        hover/current, so a stashed rect would exist only for rows that had
        already been hovered — and the first click on a fresh row is exactly the
        case that has to work.
        """
        index = self.indexAt(pos)
        if not index.isValid():
            return False
        delegate = self.itemDelegate()
        action_rect = getattr(delegate, "action_rect", None)
        if action_rect is None:
            return False
        return action_rect(self.visualRect(index), index).contains(pos)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Checked BEFORE the header's own click-to-collapse: the control
            # lives inside the header row, so without this every press on it
            # would fold the section it is trying to narrow.
            hit = self._mode_toggle_hit(event.position().toPoint())
            if hit is not None:
                self.section_mode_toggled.emit(hit[0] or "", hit[1])
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and self._action_hit(
            event.position().toPoint()
        ):
            # Routed through the SAME seam the right-click menu uses, so the
            # affordance can never offer a different menu from the gesture it
            # is a shortcut for (channel_menu.py owns what is in it).
            self.customContextMenuRequested.emit(event.position().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.middle_clicked.emit(index)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            if cell is not None and cell.facet:
                # Filter ONLY — deliberately does not fall through to the base
                # implementation, so a chip click never also changes the row
                # selection and can never collide with double-click-to-play
                # (owner decision, 2026-08-03).
                self.chip_clicked.emit(cell.facet, cell.value)
                event.accept()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._request_hydration()

    # ── Poster-thumbnail hydration wiring ────────────────────────────────────

    def set_thumbnail_hydrator(self, hydrator: Optional[ChannelThumbnailHydrator]) -> None:
        """Attach (or clear, with ``None``) the viewport-only thumbnail hydrator."""
        self._thumbnail_hydrator = hydrator
        self._request_hydration()

    def request_visible_hydration(self) -> None:
        """Public re-trigger for the visible-range hydration request.

        Called by ``MainWindow._apply_channel_list_density`` right after the
        thumbnails setting flips ON, so rows already on screen get their
        posters requested immediately instead of waiting for the next scroll.
        """
        self._request_hydration()

    def setModel(self, model) -> None:  # noqa: N802
        old = self.model()
        if old is not None:
            try:
                old.modelReset.disconnect(self._request_hydration)
                old.rowsInserted.disconnect(self._on_rows_inserted)
            except TypeError:
                pass
        super().setModel(model)
        if model is not None:
            # New rows can land WITHIN the current viewport (first page load,
            # or a page appended while the list is short) — both must trigger
            # a hydration pass, not just user-driven scroll/resize.
            model.modelReset.connect(self._request_hydration)
            model.rowsInserted.connect(self._on_rows_inserted)
        self._request_hydration()

    def _on_rows_inserted(self, *_args) -> None:
        self._request_hydration()

    def _request_hydration(self, *_args) -> None:
        if self._thumbnail_hydrator is None:
            return
        visible = self._visible_row_range()
        if visible is None:
            return
        self._thumbnail_hydrator.request_range(*visible)

    def _visible_row_range(self) -> Optional[tuple[int, int]]:
        """Return the ``(first_row, last_row)`` currently painted in the
        viewport, or ``None`` when nothing is showing (empty list / not laid
        out yet)."""
        model = self.model()
        if model is None or model.rowCount() == 0:
            return None
        viewport_rect = self.viewport().rect()
        top_index = self.indexAt(viewport_rect.topLeft())
        if not top_index.isValid():
            return None
        bottom_index = self.indexAt(QPoint(viewport_rect.left(), viewport_rect.bottom()))
        last_row = bottom_index.row() if bottom_index.isValid() else model.rowCount() - 1
        return top_index.row(), last_row
