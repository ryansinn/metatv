"""Reusable icon-only sentiment + Watch-Later action bar.

One widget for the four per-item actions the Explore trail-map shows on every row
(hover bar) and in its detail strip (secondary row):

* 👍 like / 👎 dislike / 🙅 not-interested — **mutually exclusive**: selecting one
  clears the other two; clicking the active one clears it (matches the details-pane
  ``_ActionBar`` semantics).
* 📋 Watch Later — **independent** toggle.

The bar is a *dumb view*: it flips its own checked states optimistically and emits
the intent; the host persists (and its reload re-syncs via :meth:`set_state`).  Every
glyph comes from ``icons.py``; state is conveyed by ``:checked`` fill + tooltip, never
colour alone.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from PyQt6.QtCore import pyqtSignal

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class SentimentBar(QWidget):
    """A compact 👍👎🙅📋 action bar with the shared mutual-exclusion semantics."""

    rating_clicked      = pyqtSignal(int)   # +1 like / -1 dislike (host toggles)
    suppression_toggled = pyqtSignal(bool)  # not-interested on/off
    queue_clicked       = pyqtSignal()      # Watch Later toggle

    def __init__(self, parent: QWidget | None = None, *, btn_size: int = 26) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        self._like_btn = self._mk(_icons.like_icon, "Like", btn_size)
        self._dislike_btn = self._mk(_icons.dislike_icon, "Dislike", btn_size)
        self._not_interested_btn = self._mk(
            _icons.not_interested_icon, "Not Interested — suppress from recommendations", btn_size
        )
        self._queue_btn = self._mk(_icons.queue_icon, "Add to / remove from Watch Later", btn_size)

        self._like_btn.clicked.connect(self._on_like)
        self._dislike_btn.clicked.connect(self._on_dislike)
        self._not_interested_btn.clicked.connect(self._on_not_interested)
        self._queue_btn.clicked.connect(self._on_queue)

        for b in (self._like_btn, self._dislike_btn, self._not_interested_btn, self._queue_btn):
            row.addWidget(b)

    def _mk(self, glyph: str, tip: str, size: int) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setCheckable(True)
        btn.setFlat(True)
        btn.setFixedSize(size, size)
        btn.setToolTip(tip)
        btn.setStyleSheet(_theme.RATING_BTN)
        return btn

    # -- state sync (host-driven; never fires signals) -------------------- #
    def set_state(self, *, user_rating: int, is_suppressed: bool, in_queue: bool) -> None:
        """Reflect the persisted state without emitting (call after a reload)."""
        self._like_btn.setChecked(user_rating > 0)
        self._dislike_btn.setChecked(user_rating < 0)
        self._not_interested_btn.setChecked(bool(is_suppressed))
        self._queue_btn.setChecked(bool(in_queue))

    # -- click handlers (optimistic + mutually exclusive) ----------------- #
    def _clear_sentiment_except(self, keep: QPushButton) -> None:
        for b in (self._like_btn, self._dislike_btn, self._not_interested_btn):
            if b is not keep:
                b.setChecked(False)

    def _on_like(self) -> None:
        self._clear_sentiment_except(self._like_btn)
        self.rating_clicked.emit(1)

    def _on_dislike(self) -> None:
        self._clear_sentiment_except(self._dislike_btn)
        self.rating_clicked.emit(-1)

    def _on_not_interested(self) -> None:
        checked = self._not_interested_btn.isChecked()
        self._clear_sentiment_except(self._not_interested_btn)
        self.suppression_toggled.emit(checked)

    def _on_queue(self) -> None:
        # Independent — a queue toggle never touches the sentiment trio.
        self.queue_clicked.emit()
