"""Action bar and channel action state for the details pane."""
from dataclasses import dataclass, field

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal

from metatv.gui import icons as _icons


@dataclass
class ChannelActionState:
    """All per-channel DB state needed by the action bar. Loaded asynchronously."""
    channel_id: str
    in_queue: bool = False
    rating: int = 0          # -1 / 0 / +1
    is_suppressed: bool = False
    is_hidden: bool = False


class _ActionBar(QWidget):
    """Three-row button group: Watch / Library / Sentiment.

    Signals carry no channel_id — the parent orchestrator wraps them.
    """

    play_clicked            = pyqtSignal()
    diagnose_clicked        = pyqtSignal()
    favorite_clicked        = pyqtSignal()
    queue_clicked           = pyqtSignal()
    like_clicked            = pyqtSignal()
    dislike_clicked         = pyqtSignal()
    not_interested_clicked  = pyqtSignal()
    hide_clicked            = pyqtSignal()
    unhide_clicked          = pyqtSignal()
    watchlist_clicked       = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        # Internal state (optimistic — toggled on click before DB confirms)
        self._in_queue: bool = False
        self._rating: int = 0
        self._suppressed: bool = False
        self._is_hidden: bool = False
        self._current_epg_title: str = ""
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Row 1: Watch actions (always visible)
        row1 = QHBoxLayout()
        self.play_button = QPushButton(f"{self.config.play_icon} Play")
        self.play_button.setToolTip("Play this channel")
        self.play_button.clicked.connect(self.play_clicked)
        row1.addWidget(self.play_button, 1)

        self.diagnose_button = QPushButton(f"{_icons.diagnose_icon} Diagnose")
        self.diagnose_button.setToolTip(
            "Diagnose stream quality — check if buffering is your provider or your connection"
        )
        self.diagnose_button.clicked.connect(self.diagnose_clicked)
        row1.addWidget(self.diagnose_button, 1)

        self.queue_button = QPushButton(f"{self.config.queue_icon} Add to Queue")
        self.queue_button.setToolTip("Add to Watch Queue")
        self.queue_button.clicked.connect(self._on_queue_clicked)
        row1.addWidget(self.queue_button, 1)
        layout.addLayout(row1)

        # Row 2: Library actions
        row2 = QHBoxLayout()
        self.favorite_button = QPushButton()
        self.favorite_button.setToolTip("Add to Favorites")
        self.favorite_button.clicked.connect(self.favorite_clicked)
        row2.addWidget(self.favorite_button, 1)

        self.watchlist_button = QPushButton("+ Watchlist")
        self.watchlist_button.setToolTip("Add current show to watchlist patterns")
        self.watchlist_button.clicked.connect(self.watchlist_clicked)
        self.watchlist_button.hide()
        row2.addWidget(self.watchlist_button, 1)

        self.hide_button = QPushButton(f"{self.config.hide_icon} Hide")
        self.hide_button.setToolTip("Hide this channel from all views")
        row2.addWidget(self.hide_button, 1)
        layout.addLayout(row2)

        # Row 3: Sentiment — compact, VOD only
        _STYLE = (
            "QPushButton { border: none; border-radius: 3px; padding: 2px 6px; font-size: 14px; }"
            "QPushButton:checked { background: rgba(255,255,255,0.18); }"
            "QPushButton:hover   { background: rgba(255,255,255,0.10); }"
        )
        row3 = QHBoxLayout()
        row3.addStretch()

        self.like_button = QPushButton(self.config.like_icon)
        self.like_button.setFixedHeight(22)
        self.like_button.setCheckable(True)
        self.like_button.setFlat(True)
        self.like_button.setToolTip("Like")
        self.like_button.setStyleSheet(_STYLE)
        self.like_button.clicked.connect(self._on_like_clicked)
        self.like_button.hide()
        row3.addWidget(self.like_button)

        self.not_interested_button = QPushButton(self.config.not_interested_icon)
        self.not_interested_button.setFixedHeight(22)
        self.not_interested_button.setCheckable(True)
        self.not_interested_button.setFlat(True)
        self.not_interested_button.setToolTip("Not Interested — suppress from recommendations")
        self.not_interested_button.setStyleSheet(_STYLE)
        self.not_interested_button.clicked.connect(self._on_not_interested_clicked)
        self.not_interested_button.hide()
        row3.addWidget(self.not_interested_button)

        self.dislike_button = QPushButton(self.config.dislike_icon)
        self.dislike_button.setFixedHeight(22)
        self.dislike_button.setCheckable(True)
        self.dislike_button.setFlat(True)
        self.dislike_button.setToolTip("Dislike")
        self.dislike_button.setStyleSheet(_STYLE)
        self.dislike_button.clicked.connect(self._on_dislike_clicked)
        self.dislike_button.hide()
        row3.addWidget(self.dislike_button)

        row3.addStretch()
        layout.addLayout(row3)

        # Wire hide button initial state
        self._sync_hide_button()

    # ------------------------------------------------------------------ #
    # Public interface                                                      #
    # ------------------------------------------------------------------ #

    def load(self, state: ChannelActionState) -> None:
        """Apply a fetched action state to all button labels/checked states."""
        self._in_queue = state.in_queue
        self._rating = state.rating
        self._suppressed = state.is_suppressed
        self._is_hidden = state.is_hidden
        self._sync_all()

    def set_mode(self, is_live: bool) -> None:
        """Show/hide sentiment buttons (VOD only) and watchlist button (live only)."""
        self.like_button.setVisible(not is_live)
        self.not_interested_button.setVisible(not is_live)
        self.dislike_button.setVisible(not is_live)
        self.watchlist_button.setVisible(is_live)

    def update_favorite(self, is_favorite: bool) -> None:
        if is_favorite:
            self.favorite_button.setText(f"{self.config.favorite_icon} Favorited")
            self.favorite_button.setToolTip("Remove from Favorites")
        else:
            self.favorite_button.setText(f"{self.config.unfavorite_icon} Add to Favorites")
            self.favorite_button.setToolTip("Add to Favorites")

    def update_epg_title(self, title: str, watchlist_patterns: list) -> None:
        self._current_epg_title = title
        if title:
            already = title in (watchlist_patterns or [])
            self.watchlist_button.setText(
                f"{self.config.watched_icon} On Watchlist" if already else "+ Watchlist"
            )
        else:
            self.watchlist_button.setText("+ Watchlist")

    def clear(self) -> None:
        self._in_queue = False
        self._rating = 0
        self._suppressed = False
        self._is_hidden = False
        self._current_epg_title = ""
        self._sync_all()

    # ------------------------------------------------------------------ #
    # Private click handlers                                               #
    # ------------------------------------------------------------------ #

    def _on_queue_clicked(self) -> None:
        self._in_queue = not self._in_queue
        self._sync_queue_button()
        self.queue_clicked.emit()

    def _on_like_clicked(self) -> None:
        self._rating = 0 if self._rating == 1 else 1
        self._sync_rating_buttons()
        self.like_clicked.emit()

    def _on_dislike_clicked(self) -> None:
        self._rating = 0 if self._rating == -1 else -1
        self._sync_rating_buttons()
        self.dislike_clicked.emit()

    def _on_not_interested_clicked(self) -> None:
        self._suppressed = not self._suppressed
        self.not_interested_button.setChecked(self._suppressed)
        self.not_interested_clicked.emit()

    def _on_hide_clicked(self) -> None:
        self._is_hidden = True
        self._sync_hide_button()
        self.hide_clicked.emit()

    def _on_unhide_clicked(self) -> None:
        self._is_hidden = False
        self._sync_hide_button()
        self.unhide_clicked.emit()

    # ------------------------------------------------------------------ #
    # Sync helpers                                                         #
    # ------------------------------------------------------------------ #

    def _sync_all(self) -> None:
        self._sync_queue_button()
        self._sync_rating_buttons()
        self.not_interested_button.setChecked(self._suppressed)
        self._sync_hide_button()

    def _sync_queue_button(self) -> None:
        self.queue_button.setText(
            f"{self.config.queue_icon} Remove from Queue"
            if self._in_queue
            else f"{self.config.queue_icon} Add to Queue"
        )

    def _sync_rating_buttons(self) -> None:
        self.like_button.setChecked(self._rating == 1)
        self.dislike_button.setChecked(self._rating == -1)

    def _sync_hide_button(self) -> None:
        try:
            self.hide_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        if self._is_hidden:
            self.hide_button.setText(f"{self.config.hide_icon} Unhide")
            self.hide_button.setToolTip("Unhide this channel — restore it to all views")
            self.hide_button.clicked.connect(self._on_unhide_clicked)
        else:
            self.hide_button.setText(f"{self.config.hide_icon} Hide")
            self.hide_button.setToolTip("Hide this channel from all views")
            self.hide_button.clicked.connect(self._on_hide_clicked)
