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

from PyQt6.QtCore import Qt, QModelIndex, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import QListView

from metatv.gui.channel_list_thumbnails import ChannelThumbnailHydrator


class ChannelListView(QListView):
    """``QListView`` that emits ``middle_clicked(index)`` on a middle-button press."""

    middle_clicked = pyqtSignal(QModelIndex)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumbnail_hydrator: Optional[ChannelThumbnailHydrator] = None
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(self._request_hydration)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.middle_clicked.emit(index)
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
