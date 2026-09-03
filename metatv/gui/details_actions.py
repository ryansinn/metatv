"""Action bar and channel action state for the details pane."""
import time
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from metatv.gui import cursor_affordance as _cursor
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


def _fmt_elapsed(total_seconds: float) -> str:
    """Format a playback position as ``M:SS`` (or ``H:MM:SS`` past an hour)."""
    total = max(0, int(total_seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass
class ChannelActionState:
    """All per-channel DB state needed by the action bar. Loaded asynchronously."""
    channel_id: str
    in_queue: bool = False
    rating: int = 0          # -1 / 0 / +1
    is_suppressed: bool = False
    is_hidden: bool = False
    epg_link_blocked: bool = False  # channel_id in config.epg_link_blocklist
    is_favorite: bool = False


class _SteppedLabelButton(QPushButton):
    """A button whose label steps down through shorter forms as it narrows.

    The queue button opts OUT of driving the details pane's width
    (``QSizePolicy.Ignored`` — see ``details_sections.set_action_buttons`` and
    docs/DETAILS_PANE_DESIGN.md → "Width discipline"), because a
    ``QHBoxLayout``'s minimum width is the SUM of its children's minimums: a
    button reporting its true width would floor the whole pane at "Watch Later"
    plus three chips and clip every other section off the right edge. That trap
    has recurred roughly five times and the escape hatch must stay.

    Its cost is that Qt CLIPS the label rather than shrinking it, so "Watch
    Later" rendered as "Watch Lat". Stepping the label keeps the escape hatch
    and removes the clipping: the button shows the longest form that fits, and
    "Later" carries the meaning on its own. Owner: "Later is good enough,
    people will get it."

    The label is only ever stepped from :meth:`resizeEvent`, so a button that
    has never been laid out keeps its full form — which is what a test reading
    ``.text()`` without showing the widget sees.
    """

    #: Slack for the frame and padding that ``fontMetrics`` cannot see.
    #: Deliberately generous: stepping down one form early is invisible,
    #: stepping down one form late is the clipped label this exists to prevent.
    _CHROME_PX = 20

    def __init__(self, labels: tuple[str, ...], parent=None):
        """
        Args:
            labels: Forms longest-first. The last is the floor and is used
                whenever nothing fits, so it should be something that still
                reads at any width (an icon alone, typically).
            parent: Qt parent.
        """
        super().__init__(labels[0], parent)
        self._labels = labels

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_label()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        # Also on show: a button laid out to its final size before it is first
        # shown may never receive a resize, and one event is a thin thread to
        # hang the whole label on.
        super().showEvent(event)
        self._apply_label()

    def _apply_label(self) -> None:
        """Adopt the longest label that fits the current width."""
        if self.width() <= 0:
            return          # not laid out yet — the full form stands
        avail = self.width() - self._CHROME_PX
        metrics = self.fontMetrics()
        chosen = self._labels[-1]
        for text in self._labels:
            if metrics.horizontalAdvance(text) <= avail:
                chosen = text
                break
        if self.text() != chosen:
            self.setText(chosen)


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
    * **Secondary row** (one line, under Play/Resume): ``queue_button`` ("Watch
      Later") on the LEFT, then ``like_button`` / ``not_interested_button`` /
      ``dislike_button`` right-aligned.  Position separates the collection action
      from the judgment cluster, so neither side needs a caption — and rating is
      *findable* in the main column rather than unlabelled over the poster art.
    * **Rail** (slim icon-only column left of the poster): the infrequent set —
      favorite / alert / watchlist / hide.  State is conveyed via icon-swap,
      ``:checked`` and tooltips (no labels), so the rail stays narrow.

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
    clear_epg_link_clicked  = pyqtSignal()
    trailer_clicked         = pyqtSignal()
    trailer_youtube_clicked = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        # Internal state (optimistic — toggled on click before DB confirms)
        self._in_queue: bool = False
        self._rating: int = 0
        self._suppressed: bool = False
        self._is_hidden: bool = False
        self._is_monitored: bool = False
        # True when the shown title has UNVIEWED matched content (a VOD watch-for
        # match the user hasn't acknowledged).  Paints the Alert button GREEN +
        # filled, paired with the 🚨 glyph + tooltip (colourblind-safe).
        self._has_new_match: bool = False
        self._current_epg_title: str = ""
        # Primary-button label mode.  "play" → "▶ Play" (movie/live — the "currently
        # playing" indicator may apply); "browse" → "🗂 Browse" (a series root, which
        # never plays directly, only drills in); "episode" → "▶ Play Episode" (an
        # episode selected in the series tree).  set_primary_mode() owns the label so
        # the playing indicator can never clobber a Browse / Play-Episode caption.
        self._primary_mode: str = "play"
        # Episode coordinate (e.g. "S04E05") shown in the "Play Episode: …" caption —
        # set by enter_episode_mode(), cleared by exit_episode_mode() so a later
        # Browse / Play caption never carries a stale code.
        self._episode_code: str = ""
        # "Currently playing" indicator state (green outline + live elapsed timer on
        # the Play button while the shown title is the one actively playing).
        self._is_playing: bool = False
        self._playing_base_pos: float = 0.0     # last reported playback position (s)
        self._playing_base_ts: float = 0.0      # monotonic clock when that was reported
        self._playing_timer: QTimer | None = None
        # True when the shown LIVE channel's EPG link is in config.epg_link_blocklist
        # (manually cleared via 🧹 "Clear EPG link"). Flips the rail button's
        # tooltip/behavior to the "Re-link EPG data" inverse — see set_epg_link_blocked.
        self._epg_link_blocked: bool = False
        self._setup()

    def _mk(
        self, icon: str, tooltip: str, *, checkable: bool = False, style: str | None = None
    ) -> QPushButton:
        """Build one icon-only rail button (parented to self until reparented)."""
        btn = QPushButton(icon, self)
        btn.setToolTip(tooltip)
        _theme.style_fn(btn, lambda: style or _theme.DETAIL_RAIL_BTN)
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
        _theme.style(self.play_button, "DETAIL_PLAY_BTN")
        self.play_button.clicked.connect(self.play_clicked)

        self.resume_button = QPushButton(f"{_icons.resume_from_icon} Resume", self)
        self.resume_button.setToolTip("Resume from where you left off")
        _theme.style(self.resume_button, "DETAIL_RESUME_BTN")
        self.resume_button.clicked.connect(self.resume_clicked)
        self.resume_button.hide()

        # --- Rail: infrequent icon-only actions --------------------------------
        self.favorite_button = self._mk(self.config.unfavorite_icon, "Add to Favorites")
        self.favorite_button.clicked.connect(self.favorite_clicked)

        # Queue ("Watch Later") is a tier-2 action: a full-width labeled button in
        # the primary zone (under Play/Resume), NOT an icon in the rail — it is the
        # most-likely follow-up to "not right now".  _PosterSection.set_action_buttons
        # reparents it there; state reads via :checked + tooltip.
        self.queue_button = _SteppedLabelButton(
            (
                f"{self.config.queue_icon} Watch Later",
                f"{self.config.queue_icon} Later",
                self.config.queue_icon,
            ),
            self,
        )
        self.queue_button.setCheckable(True)
        _theme.style(self.queue_button, "DETAIL_SECONDARY_BTN")
        self.queue_button.setToolTip("Add to Watch Later")
        self.queue_button.clicked.connect(self._on_queue_clicked)

        # Trailer — tier 2, its own full-width row between Play/Resume and
        # Watch Later (_PosterSection.set_action_buttons). It used to sit
        # beside Watch Later on the secondary row, but at a narrow pane it
        # consumed Watch Later's slack down to a sliver — owner-reported
        # 2026-09-03. Shown only when the provider actually sent one, which is
        # 114,308 of the owner's channels; a button that is present but dead
        # on the other 670,000 is worse than absent.
        #
        # Left-click plays it; right-click offers the same thing on YouTube, for
        # the times mpv's extractor is out of date or the viewer wants the page
        # (comments, related, a different quality). The icon trails the word
        # because the label is the noun and the glyph is the verb applied to it.
        self.trailer_button = QPushButton(f"Trailer {self.config.play_icon}", self)
        self.trailer_button.setToolTip(
            "Play the trailer  ·  right-click for more")
        _theme.style(self.trailer_button, "DETAIL_SECONDARY_BTN")
        self.trailer_button.clicked.connect(self.trailer_clicked)
        self.trailer_button.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.trailer_button.customContextMenuRequested.connect(
            self._show_trailer_menu)
        _cursor.set_clickable(self.trailer_button)
        self.trailer_button.hide()

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

        # Clear EPG link — live only (shown via set_mode); the admin-tier affordance
        # for a wrong/mismatched guide link. set_epg_link_blocked() flips the tooltip
        # to the "Re-link EPG data" inverse once the channel is blocked.
        self.clear_epg_link_button = self._mk(
            _icons.clear_epg_link_icon,
            "Clear wrong guide data — unlink this channel's EPG",
        )
        self.clear_epg_link_button.clicked.connect(self.clear_epg_link_clicked)
        self.clear_epg_link_button.hide()

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
        """Apply a fetched action state to all button checked states/tooltips.

        ``state`` is always SERIES-level (ChannelActionState). In episode mode
        (Slice 2B) queue state AND the favorite star are per-EPISODE instead —
        set via ``set_episode_queue_favorite`` — so a late-arriving series-level
        fetch (the two async requests race; either can resolve last) must not
        clobber either one. Rating/suppressed/hidden stay series-scoped even in
        episode mode by design (see enter_episode_mode /
        _refresh_series_scope_tooltips), so those always apply.
        """
        if self._primary_mode != "episode":
            self._in_queue = state.in_queue
            self.update_favorite(state.is_favorite)
        self._rating = state.rating
        self._suppressed = state.is_suppressed
        self._is_hidden = state.is_hidden
        self.set_epg_link_blocked(state.epg_link_blocked)
        self._sync_all()

    def set_trailer(self, has_trailer: bool) -> None:
        """Show the Trailer button only when there is a trailer to play.

        Args:
            has_trailer: Whether the current channel resolved a trailer URL.
        """
        self.trailer_button.setVisible(bool(has_trailer))

    def _show_trailer_menu(self, pos) -> None:
        """Right-click menu on the Trailer button.

        Two entries, because they fail in different ways: mpv plays it inline
        via yt-dlp, which is the better experience and the one that breaks when
        the extractor goes stale; the browser always works and is where the
        page's own context lives.

        Args:
            pos: Click position in the button's coordinates.
        """
        from PyQt6.QtWidgets import QMenu

        # Unstyled, like every menu in channel_menu.py: the QPalette floor
        # themes a widget with no stylesheet, which is what it is for.
        menu = QMenu(self.trailer_button)
        menu.addAction(
            f"Play trailer {self.config.play_icon}"
        ).triggered.connect(self.trailer_clicked)
        menu.addAction(
            "Play trailer on YouTube"
        ).triggered.connect(self.trailer_youtube_clicked)
        menu.exec(self.trailer_button.mapToGlobal(pos))

    def set_mode(self, is_live: bool) -> None:
        """Show/hide sentiment buttons (VOD only) and watchlist/clear-EPG-link (live only)."""
        self.like_button.setVisible(not is_live)
        self.not_interested_button.setVisible(not is_live)
        self.dislike_button.setVisible(not is_live)
        self.watchlist_button.setVisible(is_live)
        # VOD has no XMLTV guide to (mis)link — the admin action is meaningless there.
        self.clear_epg_link_button.setVisible(is_live)

    def set_monitorable(self, is_series: bool, is_monitored: bool) -> None:
        """Show the Alert button for series only; reflect the alert state."""
        self.monitor_button.setVisible(is_series)
        self._is_monitored = is_monitored
        self._sync_monitor_button()

    def set_new_match(self, has_unviewed_match: bool) -> None:
        """Flag the Alert button GREEN when the shown title has unviewed matched content.

        The green is the reserved OK/new-match colour, paired with the 🚨 glyph the
        button already carries + a tooltip — never colour-alone.  Clearing the
        match (per-item or bulk "Clear Alerts") and re-loading the title drops the
        green (the user dismisses; nothing auto-acts).
        """
        self._has_new_match = has_unviewed_match
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

    # ------------------------------------------------------------------ #
    # Primary-button label mode (Play / Browse / Play Episode)             #
    # ------------------------------------------------------------------ #

    def set_primary_mode(self, mode: str) -> None:
        """Set what the primary button says: ``"play"`` / ``"browse"`` / ``"episode"``.

        * ``"play"`` (movie/live) → ``▶ Play`` — the "currently playing" indicator
          may light this button.
        * ``"browse"`` (series root) → ``🗂 Browse`` — clicking drills into
          seasons/episodes; a series never plays directly, so the indicator is
          suppressed.
        * ``"episode"`` (episode selected in the tree) → ``▶ Play Episode``.

        Switching to a non-play mode stops any live playing indicator first, so its
        per-second tick can't overwrite the new caption.
        """
        self._primary_mode = mode
        if mode != "play":
            self.clear_playing()
        self._apply_primary_label()

    def _apply_primary_label(self) -> None:
        """Stamp the primary button's text + tooltip for the current ``_primary_mode``."""
        if self._primary_mode == "browse":
            self.play_button.setText(f"{_icons.browse_icon} Browse")
            self.play_button.setToolTip("Browse seasons & episodes")
        elif self._primary_mode == "episode":
            code = self._episode_code
            self.play_button.setText(
                f"{_icons.play_icon} Play Episode: {code}" if code
                else f"{_icons.play_icon} Play Episode"
            )
            self.play_button.setToolTip(
                f"Play this episode ({code})" if code else "Play this episode"
            )
        else:
            self.play_button.setText(f"{self.config.play_icon} Play")
            self.play_button.setToolTip("Play from the beginning")

    def enter_episode_mode(self, episode_code: str = "") -> None:
        """Configure the action bar for an episode selected in the series tree.

        The primary button becomes ``▶ Play Episode: S##E##`` (or plain
        ``▶ Play Episode`` when no coordinate is known); Resume is hidden HERE only
        so the series' position never leaks onto an episode — ``show_episode`` calls
        ``set_resume`` immediately after this, from the EPISODE's own stored
        ``watch_progress``, so an episode with a saved position does show Resume
        (#304).  Do not "restore" this to a movie-only affordance.  Watch Later STAYS VISIBLE
        and the favorite star stays clickable (Wave 2 Slice 2B) but both now target
        the EPISODE, not the series — reset to un-queued/un-favorited here so neither
        flashes the series' stale state (nor an un-suffixed tooltip); the caller's
        async per-episode fetch (``episode_action_state_requested`` →
        ``apply_episode_action_state``) corrects both shortly after.
        ``exit_episode_mode`` (called from show_channel) restores series-scoped
        behaviour.

        Args:
            episode_code: The episode coordinate to show in the caption, e.g.
                ``"S04E05"`` (or ``"E05"`` when the season is unknown).  Empty
                string → the plain ``Play Episode`` caption.
        """
        self._episode_code = episode_code
        self.set_primary_mode("episode")
        self.resume_button.hide()
        self._in_queue = False
        self._sync_queue_button()
        self.queue_button.setVisible(True)
        # Reset the favorite star too (its icon/tooltip were last painted for the
        # SERIES by show_channel(), before _episode_code existed) — re-render now
        # that _primary_mode/_episode_code are set, so the tooltip carries the
        # episode coordinate; the caller's async per-episode fetch corrects the
        # icon shortly after, same as the queue button above.
        self.update_favorite(False)
        self._refresh_series_scope_tooltips()

    def exit_episode_mode(self) -> None:
        """Undo :meth:`enter_episode_mode`'s state (label handled by caller).

        Clears the stored episode code so a later Browse / Play caption — and the
        queue/favorite tooltips — never carry a stale coordinate; Resume visibility
        is re-derived by the subsequent ``set_resume`` call in ``show_channel``.
        """
        self._episode_code = ""
        self.queue_button.setVisible(True)
        self._refresh_series_scope_tooltips()

    def _refresh_series_scope_tooltips(self) -> None:
        """Flag like/dislike/not-interested/hide as SERIES-scoped while in episode mode.

        These buttons are never re-targeted to the episode (unlike queue/favorite) —
        per the "no silent series-scoping" rule, their tooltip must say so instead
        rather than quietly rating/hiding the whole series while an episode is shown.
        ``_sync_hide_button`` re-derives its own suffix from ``_primary_mode`` on
        every call, so only the three static-tooltip buttons need refreshing here.
        """
        suffix = (
            " — applies to the whole series, not just this episode"
            if self._primary_mode == "episode" else ""
        )
        self.like_button.setToolTip(f"Like{suffix}")
        self.dislike_button.setToolTip(f"Dislike{suffix}")
        self.not_interested_button.setToolTip(
            f"Not Interested — suppress from recommendations{suffix}"
        )
        self._sync_hide_button()

    # ------------------------------------------------------------------ #
    # "Currently playing" indicator (green outline + live elapsed timer)   #
    # ------------------------------------------------------------------ #

    def set_playing_active(self, position_seconds: float) -> None:
        """Mark the Play button as the actively-playing title.

        Paints the GREEN outline state and shows a live elapsed timer
        (``▶ M:SS``) that ticks up once a second between position reports.  The
        caller pushes a fresh ``position_seconds`` roughly every couple of seconds
        (from the player position poll); the per-second QTimer interpolates in
        between so the count never stalls.  Colour is reinforcement only — the
        running timer is the non-colour cue.

        Args:
            position_seconds: The current playback position in seconds.
        """
        if self._primary_mode != "play":
            # A series-root (Browse) or episode-detail primary button is never the
            # actively-playing movie/live title — don't paint the green indicator (or
            # start the per-second tick) over its Browse / Play-Episode caption.
            return
        self._is_playing = True
        self._playing_base_pos = float(position_seconds or 0.0)
        self._playing_base_ts = time.monotonic()
        _theme.style(self.play_button, "DETAIL_PLAY_BTN_PLAYING")
        if self._playing_timer is None:
            self._playing_timer = QTimer(self)
            self._playing_timer.setInterval(1000)
            self._playing_timer.timeout.connect(self._playing_tick)
        if not self._playing_timer.isActive():
            self._playing_timer.start()
        self._playing_tick()

    def clear_playing(self) -> None:
        """Revert the Play button to its normal (not-playing) appearance."""
        if not self._is_playing:
            return
        self._is_playing = False
        if self._playing_timer is not None:
            self._playing_timer.stop()
        _theme.style(self.play_button, "DETAIL_PLAY_BTN")
        self.play_button.setText(f"{self.config.play_icon} Play")
        self.play_button.setToolTip("Play from the beginning")

    def _current_playing_position(self) -> float:
        """Interpolated playback position: last report + wall time since."""
        return self._playing_base_pos + (time.monotonic() - self._playing_base_ts)

    def _playing_tick(self) -> None:
        """Per-second tick — refresh the Play button's live elapsed label."""
        if not self._is_playing:
            return
        elapsed = _fmt_elapsed(self._current_playing_position())
        self.play_button.setText(f"{_icons.play_icon} {elapsed}")
        self.play_button.setToolTip(f"Now playing — {elapsed}")

    def update_favorite(self, is_favorite: bool) -> None:
        """Paint the favorite star. In episode mode (Slice 2B) the tooltip names the
        episode coordinate, since the click now targets the EPISODE, not the series.
        """
        suffix = f" {self._episode_code}" if (self._primary_mode == "episode" and self._episode_code) else ""
        if is_favorite:
            self.favorite_button.setText(self.config.favorite_icon)
            self.favorite_button.setToolTip(f"Remove{suffix} from Favorites")
            # Favorited glows GOLD (the star fills yellow) — the favorite button is
            # NOT :checkable, so the accent :checked rule can't reach it; swap the
            # whole style directly (mirrors the alert/monitor button's style swap).
            _theme.style(self.favorite_button, "DETAIL_RAIL_BTN_FAV")
        else:
            self.favorite_button.setText(self.config.unfavorite_icon)
            self.favorite_button.setToolTip(f"Add{suffix} to Favorites")
            _theme.style(self.favorite_button, "DETAIL_RAIL_BTN")

    def set_episode_queue_favorite(self, in_queue: bool, is_favorite: bool) -> None:
        """Apply per-EPISODE queue + favorite state (episode mode only, Slice 2B).

        Separate from :meth:`load`, which applies the SERIES-level
        ``ChannelActionState`` — rating/suppress/hide stay series-scoped even in
        episode mode (see ``enter_episode_mode``); only queue + favorite become
        episode-scoped here, driven by the pane's own per-episode DB fetch.
        """
        self._in_queue = in_queue
        self._sync_queue_button()
        self.update_favorite(is_favorite)

    def update_epg_title(self, title: str, watchlist_patterns: list) -> None:
        self._current_epg_title = title
        already = bool(title) and title in (watchlist_patterns or [])
        self.watchlist_button.setChecked(already)
        self.watchlist_button.setToolTip(
            "On watchlist — click to remove" if already
            else "Add current show to watchlist patterns"
        )

    def set_epg_link_blocked(self, blocked: bool) -> None:
        """Reflect whether the shown LIVE channel's EPG link is currently blocked.

        Flips the rail button's tooltip between the "Clear EPG link" affordance
        (unblocked — click unlinks + blocks) and its "Re-link EPG data" inverse
        (blocked — click removes the block and re-matches). Visibility (live
        channels only) is governed separately by :meth:`set_mode`.
        """
        self._epg_link_blocked = blocked
        if blocked:
            self.clear_epg_link_button.setToolTip(
                "EPG link blocked — click to re-link (re-match guide data)"
            )
        else:
            self.clear_epg_link_button.setToolTip(
                "Clear wrong guide data — unlink this channel's EPG"
            )

    def clear(self) -> None:
        self._in_queue = False
        self._rating = 0
        self._suppressed = False
        self._is_hidden = False
        self._is_monitored = False
        self._has_new_match = False
        self._current_epg_title = ""
        self.set_epg_link_blocked(False)
        self.monitor_button.setVisible(False)
        self.resume_button.setVisible(False)
        self.trailer_button.setVisible(False)
        self.watchlist_button.setChecked(False)
        self.clear_playing()
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
        if self._primary_mode == "episode" and self._episode_code:
            # Episode mode (Slice 2B): the button now queues THIS episode, not the
            # series — say so, and use "Watch Queue" (the episode-grain wording)
            # rather than the channel-grain "Watch Later" below.
            self.queue_button.setToolTip(
                f"Remove {self._episode_code} from Watch Queue" if self._in_queue
                else f"Add {self._episode_code} to Watch Queue"
            )
        else:
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
        # Episode mode (Slice 2B): Hide still targets the whole SERIES — flag it
        # rather than silently hiding more than what's shown (no silent
        # series-scoping rule).
        suffix = (
            " — hides the whole series, not just this episode"
            if self._primary_mode == "episode" else ""
        )
        if self._is_hidden:
            self.hide_button.setToolTip(f"Unhide this channel — restore it to all views{suffix}")
            self.hide_button.clicked.connect(self._on_unhide_clicked)
        else:
            self.hide_button.setToolTip(f"Hide this channel from all views{suffix}")
            self.hide_button.clicked.connect(self._on_hide_clicked)

    def _sync_monitor_button(self) -> None:
        self.monitor_button.setChecked(self._is_monitored)
        if self._has_new_match:
            # New matched content available — GREEN + filled wins over the red
            # alerting state.  🚨 glyph + tooltip carry the non-colour cue.
            _theme.style(self.monitor_button, "DETAIL_RAIL_BTN_NEW_MATCH")
            self.monitor_button.setToolTip(
                "New matched content available — right-click the item in the list "
                "to clear this alert (or use Clear Alerts in the Watch Queue)"
            )
            return
        _theme.style(self.monitor_button, "DETAIL_RAIL_BTN_ALERT")
        self.monitor_button.setToolTip(
            "Stop new-episode alerts for this series" if self._is_monitored
            else "Alert me to new episodes of this series"
        )
