"""Action bar and channel action state for the details pane."""
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget, QPushButton
from PyQt6.QtCore import pyqtSignal

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


@dataclass
class ChannelActionState:
    """All per-channel DB state needed by the action bar. Loaded asynchronously."""
    channel_id: str
    in_queue: bool = False
    rating: int = 0          # -1 / 0 / +1
    is_suppressed: bool = False
    is_hidden: bool = False


class _ActionBar(QWidget):
    """Owns every channel action button, its state, and its signals.

    This widget is the logical owner — it never appears in the content layout
    itself; the buttons are reparented into their visual slots by
    ``_PosterSection.set_action_buttons``.  Actions are tiered by interaction
    frequency:

    * **Primary zone** (full-size, labeled, below the poster): ``play_button`` and
      ``resume_button`` — the most-used actions.  Play always starts from the
      beginning; Resume continues from the saved position and is the visually
      dominant of the two when both are shown.
    * **Rail** (slim icon-only column left of the poster): the infrequent set —
      favorite / queue / sentiment / alert / watchlist / hide.  State is conveyed
      via icon-swap, ``:checked`` and tooltips (no labels), so the rail stays narrow.

    The watched state is no longer a rail button — it is a clickable poster badge
    owned by ``_PosterSection`` (the ``watched_toggled`` path lives there).

    Signals carry no channel_id — the parent orchestrator wraps them.
    """

    play_clicked            = pyqtSignal()
    resume_clicked          = pyqtSignal()
    favorite_clicked        = pyqtSignal()
    queue_clicked           = pyqtSignal()
    like_clicked            = pyqtSignal()
    dislike_clicked         = pyqtSignal()
    not_interested_clicked  = pyqtSignal()
    hide_clicked            = pyqtSignal()
    unhide_clicked          = pyqtSignal()
    watchlist_clicked       = pyqtSignal()
    monitor_clicked         = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        # Internal state (optimistic — toggled on click before DB confirms)
        self._in_queue: bool = False
        self._rating: int = 0
        self._suppressed: bool = False
        self._is_hidden: bool = False
        self._is_monitored: bool = False
        self._current_epg_title: str = ""
        self._setup()

    def _mk(
        self, icon: str, tooltip: str, *, checkable: bool = False, style: str | None = None
    ) -> QPushButton:
        """Build one icon-only rail button (parented to self until reparented)."""
        btn = QPushButton(icon, self)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(style or _theme.DETAIL_RAIL_BTN)
        if checkable:
            btn.setCheckable(True)
        return btn

    def _setup(self) -> None:
        # No layout here — every button is reparented into its visual slot by
        # set_action_buttons() (play/resume → primary row; the rest → rail).
        # _ActionBar owns state/signals/sync only.

        # --- Primary zone: full-size labeled buttons (most-used actions) ---------
        # Play always starts from the beginning (secondary/outline).  Resume
        # continues from the saved position (dominant filled-orange) and is shown
        # only when there's a saved position (movies with watch_progress > 0);
        # set_resume() toggles it and stamps the M:SS label.
        self.play_button = QPushButton(f"{self.config.play_icon} Play", self)
        self.play_button.setToolTip("Play from the beginning")
        self.play_button.setStyleSheet(_theme.DETAIL_PLAY_BTN)
        self.play_button.clicked.connect(self.play_clicked)

        self.resume_button = QPushButton(f"{_icons.resume_from_icon} Resume", self)
        self.resume_button.setToolTip("Resume from where you left off")
        self.resume_button.setStyleSheet(_theme.DETAIL_RESUME_BTN)
        self.resume_button.clicked.connect(self.resume_clicked)
        self.resume_button.hide()

        # --- Rail: infrequent icon-only actions --------------------------------
        self.favorite_button = self._mk(self.config.unfavorite_icon, "Add to Favorites")
        self.favorite_button.clicked.connect(self.favorite_clicked)

        # Queue ("Watch Later") is a tier-2 action: a full-width labeled button in
        # the primary zone (under Play/Resume), NOT an icon in the rail — it is the
        # most-likely follow-up to "not right now".  _PosterSection.set_action_buttons
        # reparents it there; state reads via :checked + tooltip.
        self.queue_button = QPushButton(
            f"{self.config.queue_icon} Watch Later", self
        )
        self.queue_button.setCheckable(True)
        self.queue_button.setStyleSheet(_theme.DETAIL_QUEUE_BTN)
        self.queue_button.setToolTip("Add to Watch Later")
        self.queue_button.clicked.connect(self._on_queue_clicked)

        self.hide_button = self._mk(self.config.hide_icon, "Hide this channel from all views")
        # hide/unhide wired in _sync_hide_button (it reconnects on state change)

        # Sentiment actions — VOD only (shown via set_mode)
        self.like_button = self._mk(self.config.like_icon, "Like", checkable=True)
        self.like_button.clicked.connect(self._on_like_clicked)
        self.like_button.hide()

        self.not_interested_button = self._mk(
            self.config.not_interested_icon,
            "Not Interested — suppress from recommendations",
            checkable=True,
        )
        self.not_interested_button.clicked.connect(self._on_not_interested_clicked)
        self.not_interested_button.hide()

        self.dislike_button = self._mk(self.config.dislike_icon, "Dislike", checkable=True)
        self.dislike_button.clicked.connect(self._on_dislike_clicked)
        self.dislike_button.hide()

        # Watchlist — live only (shown via set_mode)
        self.watchlist_button = self._mk(
            _icons.watch_later_icon, "Add current show to watchlist patterns", checkable=True
        )
        self.watchlist_button.clicked.connect(self.watchlist_clicked)
        self.watchlist_button.hide()

        # Alert / monitor — series only (shown via set_monitorable).  Uses the
        # alert style: the siren glows red when alerting (:checked).
        self.monitor_button = self._mk(
            _icons.alert_icon, "Alert me to new episodes of this series",
            checkable=True, style=_theme.DETAIL_RAIL_BTN_ALERT,
        )
        self.monitor_button.clicked.connect(self._on_monitor_clicked)
        self.monitor_button.hide()

        # Wire hide button initial state
        self._sync_hide_button()

    # ------------------------------------------------------------------ #
    # Public interface                                                      #
    # ------------------------------------------------------------------ #

    def load(self, state: ChannelActionState) -> None:
        """Apply a fetched action state to all button checked states/tooltips."""
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

    def set_monitorable(self, is_series: bool, is_monitored: bool) -> None:
        """Show the Alert button for series only; reflect the alert state."""
        self.monitor_button.setVisible(is_series)
        self._is_monitored = is_monitored
        self._sync_monitor_button()

    def set_resume(self, can_resume: bool, position_s: int = 0) -> None:
        """Show the dominant Resume button (with its M:SS label) only when there's
        a saved position to resume from.

        When ``can_resume`` is False the Resume button is hidden and the primary
        row collapses to a full-width Play (Qt skips the hidden item's stretch).
        """
        self.resume_button.setVisible(can_resume)
        if can_resume and position_s > 0:
            minutes, secs = divmod(int(position_s), 60)
            self.resume_button.setText(f"{_icons.resume_from_icon} Resume {minutes}:{secs:02d}")
            self.resume_button.setToolTip(f"Resume from {minutes}:{secs:02d}")
        else:
            self.resume_button.setText(f"{_icons.resume_from_icon} Resume")
            self.resume_button.setToolTip("Resume from where you left off")

    def update_favorite(self, is_favorite: bool) -> None:
        if is_favorite:
            self.favorite_button.setText(self.config.favorite_icon)
            self.favorite_button.setToolTip("Remove from Favorites")
        else:
            self.favorite_button.setText(self.config.unfavorite_icon)
            self.favorite_button.setToolTip("Add to Favorites")

    def update_epg_title(self, title: str, watchlist_patterns: list) -> None:
        self._current_epg_title = title
        already = bool(title) and title in (watchlist_patterns or [])
        self.watchlist_button.setChecked(already)
        self.watchlist_button.setToolTip(
            "On watchlist — click to remove" if already
            else "Add current show to watchlist patterns"
        )

    def clear(self) -> None:
        self._in_queue = False
        self._rating = 0
        self._suppressed = False
        self._is_hidden = False
        self._is_monitored = False
        self._current_epg_title = ""
        self.monitor_button.setVisible(False)
        self.resume_button.setVisible(False)
        self.watchlist_button.setChecked(False)
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
        self._clear_suppressed_for_rating()
        self._sync_rating_buttons()
        self.like_clicked.emit()

    def _on_dislike_clicked(self) -> None:
        self._rating = 0 if self._rating == -1 else -1
        self._clear_suppressed_for_rating()
        self._sync_rating_buttons()
        self.dislike_clicked.emit()

    def _on_not_interested_clicked(self) -> None:
        self._suppressed = not self._suppressed
        # Mutually exclusive with like/dislike — turning "not interested" on
        # clears any rating (the host persists the same cross-clear).
        if self._suppressed and self._rating != 0:
            self._rating = 0
            self._sync_rating_buttons()
        self.not_interested_button.setChecked(self._suppressed)
        self.not_interested_clicked.emit()

    def _clear_suppressed_for_rating(self) -> None:
        """A like/dislike is mutually exclusive with 'not interested' — clear it."""
        if self._rating != 0 and self._suppressed:
            self._suppressed = False
            self.not_interested_button.setChecked(False)

    def _on_hide_clicked(self) -> None:
        self._is_hidden = True
        self._sync_hide_button()
        self.hide_clicked.emit()

    def _on_monitor_clicked(self) -> None:
        self._is_monitored = not self._is_monitored
        self._sync_monitor_button()
        self.monitor_clicked.emit()

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
        self.queue_button.setChecked(self._in_queue)
        self.queue_button.setToolTip(
            "Remove from Watch Later" if self._in_queue else "Add to Watch Later"
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
            self.hide_button.setToolTip("Unhide this channel — restore it to all views")
            self.hide_button.clicked.connect(self._on_unhide_clicked)
        else:
            self.hide_button.setToolTip("Hide this channel from all views")
            self.hide_button.clicked.connect(self._on_hide_clicked)

    def _sync_monitor_button(self) -> None:
        self.monitor_button.setChecked(self._is_monitored)
        self.monitor_button.setToolTip(
            "Stop new-episode alerts for this series" if self._is_monitored
            else "Alert me to new episodes of this series"
        )
