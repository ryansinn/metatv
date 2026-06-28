"""Details pane — thin orchestrator that assembles section widgets."""
from typing import Optional

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.database import Database
from metatv.core.models import MediaType
from metatv.gui.epg_agenda_widget import EpgAgendaWidget
from metatv.metadata_providers.base import MetadataResult

# Section widgets
from metatv.gui.details_sections import (
    _PosterSection, _MetadataSection, _PlotSection, _TechnicalSection, _CastSection,
    _TagsSection,
)
from metatv.gui.details_actions import ChannelActionState, _ActionBar
from metatv.gui import icons as _icons
from metatv.gui.details_versions import ChannelVersion, _VersionSection
from metatv.gui.details_similar import _SimilarSection


class DetailsPaneWidget(QWidget):
    """Right-side details pane showing channel metadata.

    All DB state is loaded asynchronously via action_state_requested →
    apply_action_state(). Section widgets are pure renderers.
    """

    # Public signals — wired by main_window (unchanged API)
    play_requested             = pyqtSignal(str)        # channel_id
    play_version_requested     = pyqtSignal(str)        # channel_id — play a specific source variant
    favorite_toggled           = pyqtSignal(str)        # channel_id
    monitor_toggled            = pyqtSignal(str)        # channel_id (series monitor toggle)
    queue_toggled              = pyqtSignal(str)        # channel_id
    rating_requested           = pyqtSignal(str, int)   # channel_id, ±1
    suppression_requested      = pyqtSignal(str, bool)  # channel_id, suppressed
    hide_requested             = pyqtSignal(str)        # channel_id
    unhide_requested           = pyqtSignal(str)        # channel_id
    channel_versions_requested = pyqtSignal(str)        # channel_id
    version_selected           = pyqtSignal(str)        # channel_id — show details
    prefix_block_requested     = pyqtSignal(str)        # prefix
    prefix_unblock_requested   = pyqtSignal(str)        # prefix
    prefix_name_saved          = pyqtSignal(str, str)   # prefix, name
    manage_filters_requested   = pyqtSignal()
    genre_filter_requested     = pyqtSignal(str)        # genre name
    person_filter_requested    = pyqtSignal(str)        # person name
    similar_titles_requested   = pyqtSignal(str)        # channel_id
    similar_preview_requested  = pyqtSignal(list, int, str)
    action_state_requested     = pyqtSignal(str)        # channel_id — triggers async DB load
    channel_tags_requested     = pyqtSignal(str)        # channel_id — triggers async tags load
    poster_enlarged            = pyqtSignal(QPixmap)    # full-res pixmap — open lightbox

    def __init__(self, config, image_cache, db: Database | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.image_cache = image_cache
        self._db = db
        self.current_channel = None
        self.current_metadata: MetadataResult | None = None
        self.provider_urls: list = []
        self._provider_map: dict = {}

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

        # Tier 1: instant display from channel attributes
        self._meta.load_basic(channel, self._provider_map)
        self._action_bar.update_favorite(channel.is_favorite)
        _is_series = getattr(channel, "media_type", None) == MediaType.SERIES
        _is_mon = False
        _check = getattr(self.config, "is_series_monitored", None)
        if _is_series and callable(_check):
            _is_mon = bool(_check(channel.id))
        self._action_bar.set_monitorable(_is_series, _is_mon)

        if is_live:
            self._poster.set_country_info(channel.name)
            logo = getattr(channel, "logo_url", None)
            if logo:
                self._poster.load_logo(logo)

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

        # Async fetches
        self.action_state_requested.emit(channel.id)
        self.channel_tags_requested.emit(channel.id)
        self.channel_versions_requested.emit(channel.id)
        if not is_live and getattr(channel, "detected_prefix", None):
            self.similar_titles_requested.emit(channel.id)

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

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(10, 10, 10, 10)
        self._content_layout.setSpacing(10)

        self._poster   = _PosterSection(self.config, self.image_cache)
        self._meta     = _MetadataSection(self.config)
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
            self._poster, self._meta, self._versions,
            self._plot, self._cast, self._tech, self._tags, self._similar,
        ):
            self._content_layout.addWidget(widget)

        self._epg_agenda = EpgAgendaWidget(self._db, self.config) if self._db else None
        if self._epg_agenda:
            self._content_layout.addWidget(self._epg_agenda)
            self._epg_agenda.now_title_changed.connect(self._on_epg_title_changed)

        # Wire ALL action buttons into the poster's left rail.  _ActionBar owns all
        # state/signals; _PosterSection just provides the visual slot (fixed-width
        # left column left of the poster).  Must happen after both are constructed.
        self._poster.set_action_buttons(
            favorite=self._action_bar.favorite_button,
            play=self._action_bar.play_button,
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
        main_layout.addWidget(scroll)

        # Resizable width range — NOT a fixed width.  setFixedWidth() pins
        # min==max so the enclosing QSplitter handle can't drag-resize the pane
        # at all (the "details resize bar does nothing" bug); the saved width is
        # already applied by MainWindow via main_splitter.setSizes(), and live
        # drags persist through the debounced layout save.
        self.setMinimumWidth(300)
        self.setMaximumWidth(500)

    def _connect_sections(self) -> None:
        """Wire internal section signals to public DetailsPaneWidget signals."""
        # Poster lightbox
        self._poster.poster_enlarged.connect(self.poster_enlarged)

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
        if metadata.plot:
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
        if self.current_channel:
            self.play_requested.emit(self.current_channel.id)

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

    # ------------------------------------------------------------------ #
    # Collapse state persistence                                           #
    # ------------------------------------------------------------------ #

    def _save_tech_state(self) -> None:
        self._tech.save_state(self.config)

    def _save_cast_state(self) -> None:
        self._cast.save_state(self.config)

    def _save_tags_state(self) -> None:
        self._tags.save_state(self.config)
