"""Details pane — thin orchestrator that assembles section widgets."""
import time
from typing import Optional

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame, QLabel,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.database import Database
from metatv.core.models import MediaType
from metatv.gui.epg_agenda_widget import EpgAgendaWidget
from metatv.metadata_providers.base import MetadataResult

# Section widgets
from metatv.gui.details_sections import (
    _PosterSection, _MetadataSection, _PlotSection, _TechnicalSection, _CastSection,
    _TagsSection, _no_width_force,
)
from metatv.gui.details_actions import ChannelActionState, _ActionBar
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_versions import ChannelVersion, _VersionSection
from metatv.gui.details_similar import _SimilarSection


class DetailsPaneWidget(QWidget):
    """Right-side details pane showing channel metadata.

    All DB state is loaded asynchronously via action_state_requested →
    apply_action_state(). Section widgets are pure renderers.
    """

    # Public signals — wired by main_window (unchanged API)
    play_requested             = pyqtSignal(str)        # channel_id
    resume_requested           = pyqtSignal(str)        # channel_id — resume from saved position
    play_version_requested     = pyqtSignal(str)        # channel_id — play a specific source variant
    favorite_toggled           = pyqtSignal(str)        # channel_id
    monitor_toggled            = pyqtSignal(str)        # channel_id (series monitor toggle)
    queue_toggled              = pyqtSignal(str)        # channel_id
    rating_requested           = pyqtSignal(str, int)   # channel_id, ±1
    suppression_requested      = pyqtSignal(str, bool)  # channel_id, suppressed
    hide_requested             = pyqtSignal(str)        # channel_id
    unhide_requested           = pyqtSignal(str)        # channel_id
    watched_toggled            = pyqtSignal(str, bool)  # channel_id, is_watched (VOD)
    channel_versions_requested = pyqtSignal(str)        # channel_id
    version_selected           = pyqtSignal(str)        # channel_id — show details
    prefix_block_requested     = pyqtSignal(str)        # prefix
    prefix_unblock_requested   = pyqtSignal(str)        # prefix
    prefix_name_saved          = pyqtSignal(str, str)   # prefix, name
    manage_filters_requested   = pyqtSignal()
    genre_filter_requested     = pyqtSignal(str)        # genre name
    person_filter_requested    = pyqtSignal(str)        # person name
    tag_filter_requested       = pyqtSignal(str, str)   # (facet_type, value) — left-click tag chip
    tag_discover_requested     = pyqtSignal(str, str)   # (facet_type, value) — right-click tag chip
    similar_titles_requested   = pyqtSignal(str)        # channel_id
    similar_preview_requested  = pyqtSignal(list, int, str)
    action_state_requested     = pyqtSignal(str)        # channel_id — triggers async DB load
    channel_tags_requested     = pyqtSignal(str)        # channel_id — triggers async tags load
    poster_enlarged            = pyqtSignal(QPixmap)    # full-res pixmap — open lightbox
    play_episode_requested     = pyqtSignal()           # play the episode shown in the pane (read current_episode)

    def __init__(self, config, image_cache, db: Database | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.image_cache = image_cache
        self._db = db
        self.current_channel = None
        self.current_metadata: MetadataResult | None = None
        # Episode-detail mode: when an episode is selected in the series tree the pane
        # keeps the SERIES as current_channel but overlays episode-specific bits (byline,
        # plot/poster fallback, "Play Episode" button).  current_episode holds the DTO the
        # host reads on play_episode_requested; _in_episode_mode routes the Play click.
        self.current_episode = None
        self._in_episode_mode: bool = False
        self.provider_urls: list = []
        self._provider_map: dict = {}
        # "Currently playing" indicator — last play-state report from the host's
        # player-position poll; the green Play-button outline + live timer fire only
        # while the shown channel matches _playing_channel_id.
        self._playing_channel_id: str | None = None
        self._playing_base_pos: float = 0.0
        self._playing_base_ts: float = 0.0

        self._setup_ui()
        self._connect_sections()

        self.image_cache.image_loaded.connect(self._on_image_loaded)
        self.image_cache.image_failed.connect(self._on_image_failed)

    # ------------------------------------------------------------------ #
    # Public API (unchanged from previous version)                         #
    # ------------------------------------------------------------------ #

    def set_provider_urls(self, urls: list) -> None:
        self.provider_urls = urls
        self._poster.set_provider_urls(urls)

    def set_provider_map(self, provider_map: dict) -> None:
        self._provider_map = provider_map

    def set_versions(self, versions: list[ChannelVersion]) -> None:
        self._versions.load(versions, provider_map=self._provider_map)

    def set_similar_titles(self, titles: list[ChannelVersion]) -> None:
        origin = self.current_channel.name if self.current_channel else ""
        self._similar.load(titles, origin)

    def set_recommendation_reason(self, reason: str | None) -> None:
        self._meta.set_recommendation_reason(reason)

    def set_playing(self, channel_id: str | None, position_seconds: float = 0.0) -> None:
        """Report which channel is actively playing, and its position.

        Called from the host's player-position poll (the same mpv poll that drives
        the nav-bar playback-health readout).  The green "currently playing"
        indicator + live elapsed timer appear on the Play button only while
        ``channel_id`` matches the title currently shown in the pane.  Pass
        ``channel_id=None`` (or a different id) when playback stops or moves to
        another title to clear the indicator.

        Args:
            channel_id: The channel id now playing, or None when nothing plays.
            position_seconds: Current playback position in seconds.
        """
        self._playing_channel_id = channel_id
        if channel_id is not None:
            self._playing_base_pos = float(position_seconds or 0.0)
            self._playing_base_ts = time.monotonic()
        self._apply_playing_indicator()

    def _apply_playing_indicator(self) -> None:
        """Show the playing indicator iff the shown channel is the one playing."""
        ch = self.current_channel
        if (ch is not None and self._playing_channel_id is not None
                and getattr(ch, "id", None) == self._playing_channel_id):
            pos = self._playing_base_pos + (time.monotonic() - self._playing_base_ts)
            self._action_bar.set_playing_active(pos)
        else:
            self._action_bar.clear_playing()

    def apply_action_state(self, state: ChannelActionState) -> None:
        """Called from main_window when the async DB load completes."""
        if not self.current_channel or self.current_channel.id != state.channel_id:
            return  # stale response — user already moved on
        self._action_bar.load(state)

    def apply_channel_tags(self, channel_id: str, tags: list) -> None:
        """Called from main_window when the async tag load completes.

        Args:
            channel_id: The channel these tags belong to — used as a stale-drop guard.
            tags: List of ChannelTagDTO objects; empty list hides the section.
        """
        if not self.current_channel or self.current_channel.id != channel_id:
            return  # stale response — user already moved on
        self._tags.load(tags)

    def show_channel(self, channel, metadata: Optional[MetadataResult] = None) -> None:
        """Display a channel. Triggers async version/similar/action-state fetches."""
        logger.debug(f"show_channel: {channel.name}, metadata={metadata is not None}")
        self.current_channel = channel
        self.current_metadata = metadata
        is_live = getattr(channel, "media_type", None) == MediaType.LIVE

        # Configure sections for channel type before clearing (reduces flicker)
        self._configure_for(is_live)

        # Clear all sections
        for s in (self._poster, self._meta, self._plot, self._tech,
                  self._cast, self._action_bar):
            s.clear()
        self._tags.clear()
        if metadata is None:
            self._versions.clear()
            self._similar.clear()

        # Reset episode-detail mode — show_channel always renders a whole channel
        # (series root / movie / live), never a single episode.  Drop the byline,
        # forget any stored episode, and un-hide the movie-only affordances the
        # episode view had hidden.
        self._in_episode_mode = False
        self.current_episode = None
        self._byline.hide()
        self._action_bar.exit_episode_mode()

        # Tier 1: instant display from channel attributes
        self._meta.load_basic(channel, self._provider_map)
        self._action_bar.update_favorite(channel.is_favorite)
        _is_series = getattr(channel, "media_type", None) == MediaType.SERIES
        # Primary button caption: a SERIES root drills in (🗂 Browse); movies/live
        # play (▶ Play).  The click behaviour is unchanged — play_requested still
        # fires; the host's series branch drills in.
        self._action_bar.set_primary_mode("browse" if _is_series else "play")
        _is_mon = False
        _check = getattr(self.config, "is_series_monitored", None)
        if _is_series and callable(_check):
            _is_mon = bool(_check(channel.id))
        self._action_bar.set_monitorable(_is_series, _is_mon)

        # Alert-visibility green: flag the Alert button when this title has UNVIEWED
        # matched content (a VOD watch-for match the user hasn't acknowledged).
        _unviewed = getattr(self.config, "is_vod_match_unviewed", None)
        _has_match = bool(_unviewed(channel.id)) if callable(_unviewed) else False
        self._action_bar.set_new_match(_has_match)

        # Resume button — movies with a saved, incomplete position only.
        _is_movie = getattr(channel, "media_type", None) == MediaType.MOVIE
        _progress = int(getattr(channel, "watch_progress", 0) or 0)
        _completed = bool(getattr(channel, "watch_completed", False))
        self._action_bar.set_resume(_is_movie and _progress > 0 and not _completed, _progress)

        # Watched badge (VOD only) — reflect the stored watch_completed flag on the
        # clickable poster badge.  (For live, set_mode already hides the badge.)
        if not is_live:
            self._poster.set_watched(_completed)

        if is_live:
            self._poster.set_country_info(channel.name)
            logo = getattr(channel, "logo_url", None)
            if logo:
                self._poster.load_live_logo(logo)

        # EPG agenda (live only)
        if self._epg_agenda:
            if is_live:
                self._epg_agenda.load_for_channel(channel.id)
            else:
                self._epg_agenda.clear()

        # Tier 2/3: enriched metadata
        if metadata:
            self._apply_metadata(metadata)
        elif not is_live:
            self._plot.show_loading(_icons.loading_icon)
            self._poster.poster_label.setText(f"{_icons.loading_icon} Loading poster...")

        # Re-evaluate the "currently playing" indicator for the new title: the
        # action_bar.clear() above reset it; light it back up if this title is the
        # one actively playing (the per-2s position poll keeps it fresh after).
        self._apply_playing_indicator()

        # Async fetches
        self.action_state_requested.emit(channel.id)
        self.channel_tags_requested.emit(channel.id)
        self.channel_versions_requested.emit(channel.id)
        if not is_live and getattr(channel, "detected_prefix", None):
            self.similar_titles_requested.emit(channel.id)

    def show_episode(self, episode, series_channel, display_title=None) -> None:
        """Display a single episode, reusing the parent series' details as fallback.

        The SERIES stays the pane's ``current_channel`` — its title, rail actions,
        versions and tags remain the series'.  Only the episode-specific surface
        changes: a wrapping byline carrying the episode title, the episode plot (or
        the series plot when the DTO has none), the episode image (or the series
        poster when the DTO has none), and a ``▶ Play Episode: S##E##`` primary
        button.  No heavy metadata is fetched synchronously — whatever the series is
        already showing is the fallback.

        Clicking Play Episode fires the bare ``play_episode_requested`` signal; the
        host reads :attr:`current_episode`.  Selecting a season / the series root
        reverts the pane via :meth:`show_channel`.

        Args:
            episode: The :class:`~metatv.core.repositories.dtos.EpisodeDTO` to show.
            series_channel: The parent series channel (the mixin's ``current_series``).
            display_title: The CLEANED episode title (what the series tree shows —
                ``series - SxxExx -`` prefixes stripped).  When ``None`` the byline
                falls back to the DTO's raw ``title`` (then ``Episode <n>``).
        """
        if series_channel is None or episode is None:
            return

        # Establish the series context if the pane isn't already showing this series
        # — its title / rail / poster / plot are the fallback surface for the episode.
        # When the user is paging through episodes of the already-shown series this is
        # a no-op, so we don't clear + re-fetch on every episode click (race-free).
        cur = self.current_channel
        if cur is None or getattr(cur, "id", None) != getattr(series_channel, "id", None):
            self.show_channel(series_channel)

        self.current_episode = episode
        self._in_episode_mode = True

        # Byline — the cleaned episode title (matches the tree row); fall back to the
        # DTO's raw title when the host didn't pass one.  Never overwrite the series
        # title above it.
        ep_title = (
            display_title
            or getattr(episode, "title", None)
            or f"Episode {getattr(episode, 'episode_num', '?')}"
        )
        self._byline.setText(ep_title)
        self._byline.setToolTip(ep_title)
        self._byline.show()

        # Plot — episode plot if the DTO carries one, else keep the series plot.
        ep_plot = getattr(episode, "plot", None)
        if ep_plot:
            self._plot.load(ep_plot)

        # Poster — episode image if the DTO carries one, else keep the series poster.
        ep_image = (
            getattr(episode, "image_url", None)
            or getattr(episode, "poster_url", None)
            or getattr(episode, "image", None)
        )
        if ep_image:
            self._poster.load_poster(ep_image, self.provider_urls)

        # Episode coordinate for the button caption — derived defensively from the DTO.
        s = getattr(episode, "season_num", None)
        e = getattr(episode, "episode_num", None)
        code = f"S{s:02d}E{e:02d}" if (s and e) else (f"E{e:02d}" if e else "")

        # Primary button → "Play Episode: S##E##"; hide movie-only Resume + Watch Later.
        self._action_bar.enter_episode_mode(code)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll

        content = QWidget()
        self._content = content
        self._content_layout = QVBoxLayout(content)
        # Reserve a hard right gutter for the vertical scrollbar so the poster / text can
        # never slide under it or off the right edge (a hard right boundary).  On themes
        # with an overlay scrollbar the content would otherwise extend the full viewport
        # width and the scrollbar would paint over the last ~15px.
        _sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        # Right gutter ≈ half what it was: the container-width authority (see
        # _sync_content_width) already keeps content off the scrollbar, so the old full
        # 10+scrollbar reservation read as a too-wide right gap.  Halve it for a tighter,
        # more symmetric inset while still clearing an overlay scrollbar.
        self._content_layout.setContentsMargins(10, 10, (10 + _sb) // 2, 10)
        self._content_layout.setSpacing(10)

        self._poster   = _PosterSection(self.config, self.image_cache)
        self._meta     = _MetadataSection(self.config)
        # Episode byline — the episode title, shown just under the title/meta area only
        # in episode mode (normally hidden).  MUST word-wrap AND opt out of driving the
        # column width (via _no_width_force) so a long/odd episode title can never widen
        # the pane or clip content off the right edge (docs/DETAILS_PANE_DESIGN.md →
        # "Width discipline").
        self._byline = QLabel()
        self._byline.setWordWrap(True)
        self._byline.setStyleSheet(_theme.DETAIL_EPISODE_BYLINE)
        _no_width_force(self._byline)
        self._byline.hide()
        self._versions = _VersionSection(self.config)
        self._action_bar = _ActionBar(self.config)
        self._plot     = _PlotSection()
        self._tech     = _TechnicalSection(self.config)
        self._cast     = _CastSection(self.config)
        self._tags     = _TagsSection(self.config)
        self._similar  = _SimilarSection(self.config)

        # Restore collapse state
        self._tech.restore_collapse_state(self.config.details_pane_collapsed_sections)
        self._cast.restore_collapse_state(self.config.details_pane_collapsed_sections)
        self._tags.restore_collapse_state(self.config.details_pane_collapsed_sections)

        # NOTE: _action_bar is intentionally NOT added to the content layout — it is
        # the logical owner of the action buttons, which are reparented into the
        # poster's left rail by set_action_buttons() below.
        for widget in (
            self._poster, self._meta, self._byline, self._versions,
            self._plot, self._cast, self._tech, self._tags, self._similar,
        ):
            self._content_layout.addWidget(widget)

        self._epg_agenda = EpgAgendaWidget(self._db, self.config) if self._db else None
        if self._epg_agenda:
            self._content_layout.addWidget(self._epg_agenda)
            self._epg_agenda.now_title_changed.connect(self._on_epg_title_changed)

        # Wire action buttons into their tiered visual slots.  _ActionBar owns all
        # state/signals; _PosterSection provides the slots (Play/Resume → primary
        # row below the poster; the rest → the slim rail).  Must happen after both
        # are constructed.
        self._poster.set_action_buttons(
            favorite=self._action_bar.favorite_button,
            play=self._action_bar.play_button,
            resume=self._action_bar.resume_button,
            queue=self._action_bar.queue_button,
            like=self._action_bar.like_button,
            not_interested=self._action_bar.not_interested_button,
            dislike=self._action_bar.dislike_button,
            watchlist=self._action_bar.watchlist_button,
            monitor=self._action_bar.monitor_button,
            hide=self._action_bar.hide_button,
        )

        self._content_layout.addStretch()
        scroll.setWidget(content)
        # Container is the width authority: cap the content widget to the viewport so no
        # child section can ever floor the column wider than the pane (h-scroll is off, so
        # an over-wide child would clip every section's right edge).  Responsive children
        # (wrapping labels, flow layouts) reflow within; nothing can push past the
        # container.  This is the structural guarantee that replaces per-label width
        # opt-outs (the recurring "content clips off the right edge" trap).
        scroll.viewport().installEventFilter(self)
        self._sync_content_width()
        main_layout.addWidget(scroll)

        # Resizable width range — NOT a fixed width.  setFixedWidth() pins
        # min==max so the enclosing QSplitter handle can't drag-resize the pane
        # at all (the "details resize bar does nothing" bug); the saved width is
        # already applied by MainWindow via main_splitter.setSizes(), and live
        # drags persist through the debounced layout save.
        self.setMinimumWidth(300)
        self.setMaximumWidth(500)

    def _sync_content_width(self) -> None:
        """Pin the content widget's max width to the viewport — the container ceiling."""
        if hasattr(self, "_content") and hasattr(self, "_scroll"):
            self._content.setMaximumWidth(self._scroll.viewport().width())

    def eventFilter(self, obj, event):
        """Keep the content width pinned to the viewport on every viewport resize."""
        if obj is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._sync_content_width()
        return super().eventFilter(obj, event)

    def _connect_sections(self) -> None:
        """Wire internal section signals to public DetailsPaneWidget signals."""
        # Poster lightbox + clickable Watched badge
        self._poster.poster_enlarged.connect(self.poster_enlarged)
        self._poster.watched_toggled.connect(self._on_watched)

        # Version chips
        v = self._versions
        v.version_selected.connect(self.version_selected)
        v.play_version_requested.connect(self.play_version_requested)
        v.favorite_toggled.connect(self.favorite_toggled)
        v.queue_toggled.connect(self.queue_toggled)
        v.hide_requested.connect(self.hide_requested)
        v.prefix_block_requested.connect(self.prefix_block_requested)
        v.prefix_unblock_requested.connect(self.prefix_unblock_requested)
        v.prefix_name_saved.connect(self.prefix_name_saved)
        v.manage_filters_requested.connect(self.manage_filters_requested)

        # Genre chips
        self._meta.genre_clicked.connect(self.genre_filter_requested)

        # Cast / director / crew person chips
        self._cast.person_clicked.connect(self.person_filter_requested)

        # Tag / collection chips — left-click filters, right-click opens Discover.
        self._tags.tag_filter_clicked.connect(self.tag_filter_requested)
        self._tags.tag_discover_clicked.connect(self.tag_discover_requested)

        # Similar titles
        s = self._similar
        s.play_requested.connect(self.play_requested)
        s.version_selected.connect(self.version_selected)
        s.favorite_toggled.connect(self.favorite_toggled)
        s.queue_toggled.connect(self.queue_toggled)
        s.prefix_exclude_requested.connect(self.prefix_block_requested)
        s.similar_preview_requested.connect(self.similar_preview_requested)

        # Action bar — wrap with channel_id
        ab = self._action_bar
        ab.play_clicked.connect(self._on_play)
        ab.resume_clicked.connect(self._on_resume)
        ab.favorite_clicked.connect(self._on_favorite)
        ab.queue_clicked.connect(self._on_queue)
        ab.like_clicked.connect(self._on_like)
        ab.dislike_clicked.connect(self._on_dislike)
        ab.not_interested_clicked.connect(self._on_not_interested)
        ab.hide_clicked.connect(self._on_hide)
        ab.unhide_clicked.connect(self._on_unhide)
        ab.watchlist_clicked.connect(self._on_watchlist)
        ab.monitor_clicked.connect(self._on_monitor)

        # Collapse state persistence
        self._tech._toggle_btn.clicked.connect(self._save_tech_state)
        self._cast._toggle_btn.clicked.connect(self._save_cast_state)
        self._tags._toggle_btn.clicked.connect(self._save_tags_state)

    def _configure_for(self, is_live: bool) -> None:
        self._poster.set_mode(is_live)
        self._meta.set_mode(is_live)
        self._plot.set_mode(is_live)
        self._tech.set_mode(is_live)
        self._cast.set_mode(is_live)
        self._action_bar.set_mode(is_live)

    def _apply_metadata(self, metadata: MetadataResult) -> None:
        self._meta.load_metadata(metadata)
        # Always route through _plot.load — it shows the section when a plot is
        # present and hides the whole 'Overview' box when it is empty.
        self._plot.load(metadata.plot)
        if metadata.poster_url:
            self._poster.load_poster(metadata.poster_url, self.provider_urls)
        else:
            self._poster.poster_label.setText("No poster available")

        weights = self._fetch_weights()
        self._tech.load(metadata, weights)
        self._cast.load(metadata.cast or [], director=metadata.director, weights=weights)

    def _fetch_weights(self):
        """Fetch preference weights for cast/director annotation. Returns None on failure."""
        if not self._db:
            return None
        try:
            from metatv.core.preference_engine import compute_weights
            session = self._db.get_session()
            try:
                w = compute_weights(session)
                return None if w.is_empty() else w
            finally:
                session.close()
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Image callbacks                                                      #
    # ------------------------------------------------------------------ #

    def _on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        self._poster.on_image_loaded(url, pixmap)

    def _on_image_failed(self, url: str, error: str) -> None:
        self._poster.on_image_failed(url, error)

    # ------------------------------------------------------------------ #
    # EPG                                                                  #
    # ------------------------------------------------------------------ #

    def _on_epg_title_changed(self, title: str) -> None:
        self._action_bar.update_epg_title(title, self.config.epg_watchlist_patterns or [])

    def _on_watchlist(self) -> None:
        title = self._action_bar._current_epg_title
        if not title:
            return
        patterns = list(self.config.epg_watchlist_patterns or [])
        if title in patterns:
            patterns.remove(title)
        else:
            patterns.append(title)
        self.config.epg_watchlist_patterns = patterns
        self.config.save()
        self._action_bar.update_epg_title(title, patterns)

    # ------------------------------------------------------------------ #
    # Action bar wrappers (add channel_id to signals)                      #
    # ------------------------------------------------------------------ #

    def _on_play(self) -> None:
        # In episode mode the primary button plays the selected episode, not the
        # series channel — emit the bare episode signal (host reads current_episode).
        if self._in_episode_mode:
            if self.current_episode is not None:
                self.play_episode_requested.emit()
            return
        if self.current_channel:
            self.play_requested.emit(self.current_channel.id)

    def _on_resume(self) -> None:
        if self.current_channel:
            self.resume_requested.emit(self.current_channel.id)

    def _on_favorite(self) -> None:
        if self.current_channel:
            self.favorite_toggled.emit(self.current_channel.id)

    def _on_monitor(self) -> None:
        if self.current_channel:
            self.monitor_toggled.emit(self.current_channel.id)

    def _on_queue(self) -> None:
        if self.current_channel:
            self.queue_toggled.emit(self.current_channel.id)

    def _on_like(self) -> None:
        if self.current_channel:
            self.rating_requested.emit(self.current_channel.id, 1)

    def _on_dislike(self) -> None:
        if self.current_channel:
            self.rating_requested.emit(self.current_channel.id, -1)

    def _on_not_interested(self) -> None:
        if self.current_channel:
            suppressed = self._action_bar._suppressed
            self.suppression_requested.emit(self.current_channel.id, suppressed)

    def _on_hide(self) -> None:
        if self.current_channel:
            self.hide_requested.emit(self.current_channel.id)

    def _on_unhide(self) -> None:
        if self.current_channel:
            self.unhide_requested.emit(self.current_channel.id)

    def _on_watched(self, is_watched: bool) -> None:
        if self.current_channel:
            # The poster badge carries the new optimistic state; route it to the
            # host's shared mark/unmark chokepoint.
            self.watched_toggled.emit(self.current_channel.id, is_watched)

    # ------------------------------------------------------------------ #
    # Collapse state persistence                                           #
    # ------------------------------------------------------------------ #

    def _save_tech_state(self) -> None:
        self._tech.save_state(self.config)

    def _save_cast_state(self) -> None:
        self._cast.save_state(self.config)

    def _save_tags_state(self) -> None:
        self._tags.save_state(self.config)
