"""Details pane widget - shows metadata for selected channel"""
import re as _re
from typing import Optional

from loguru import logger

# Regex to extract the category/country prefix from channel names like
# "BE ★ Channel Name", "ARGENTINA ★ ...", "EPL ★ ...", "EFL-L1 ★ ..."
_CHANNEL_PREFIX_RE = _re.compile(r'^([A-Z][A-Z0-9\-]{1,11})\s*([★|])\s*(.+)$')

_COUNTRY_ABBREV_DP: dict[str, str] = {
    "ARGENTINA": "ARG", "AUSTRALIA": "AUS", "AUSTRIA": "AUT",
    "BELGIUM": "BEL", "BOLIVIA": "BOL", "BRAZIL": "BRA",
    "CANADA": "CAN", "CHILE": "CHL", "COLOMBIA": "COL",
    "CROATIA": "HRV", "DENMARK": "DEN", "ECUADOR": "ECU",
    "FINLAND": "FIN", "FRANCE": "FRA", "GERMANY": "GER",
    "GREECE": "GRE", "HUNGARY": "HUN", "IRELAND": "IRL",
    "ITALY": "ITA", "MEXICO": "MEX", "NETHERLANDS": "NED",
    "NORWAY": "NOR", "PARAGUAY": "PAR", "PERU": "PER",
    "POLAND": "POL", "PORTUGAL": "POR", "ROMANIA": "ROU",
    "RUSSIA": "RUS", "SPAIN": "ESP", "SWEDEN": "SWE",
    "SWITZERLAND": "SUI", "TURKEY": "TUR", "UKRAINE": "UKR",
    "URUGUAY": "URY", "VENEZUELA": "VEN",
}

_CATEGORY_FULL_NAMES_DP: dict[str, str] = {
    "US": "United States", "UK": "United Kingdom", "GB": "United Kingdom",
    "BE": "Belgium", "FR": "France", "DE": "Germany", "ES": "Spain",
    "IT": "Italy", "PT": "Portugal", "NL": "Netherlands", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland",
    "RO": "Romania", "HU": "Hungary", "CZ": "Czech Republic", "GR": "Greece",
    "TR": "Turkey", "RU": "Russia", "UA": "Ukraine", "BR": "Brazil",
    "MX": "Mexico", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
    "JP": "Japan", "KR": "South Korea", "CN": "China", "IN": "India",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "VE": "Venezuela", "IR": "Iran", "SA": "Saudi Arabia", "AE": "UAE",
    "EG": "Egypt", "MA": "Morocco", "IL": "Israel", "ZA": "South Africa",
    "AT": "Austria", "CH": "Switzerland", "IE": "Ireland", "HR": "Croatia",
    "SK": "Slovakia", "SI": "Slovenia", "BG": "Bulgaria", "RS": "Serbia",
    "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium",
    "BOL": "Bolivia", "BRA": "Brazil", "CAN": "Canada", "CHL": "Chile",
    "COL": "Colombia", "HRV": "Croatia", "DEN": "Denmark", "ECU": "Ecuador",
    "FIN": "Finland", "FRA": "France", "GER": "Germany", "GRE": "Greece",
    "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "MEX": "Mexico",
    "NED": "Netherlands", "NOR": "Norway", "PAR": "Paraguay", "PER": "Peru",
    "POL": "Poland", "POR": "Portugal", "ROU": "Romania", "RUS": "Russia",
    "ESP": "Spain", "SWE": "Sweden", "SUI": "Switzerland", "TUR": "Turkey",
    "UKR": "Ukraine", "URY": "Uruguay", "VEN": "Venezuela",
    "EPL": "English Premier League", "EFL": "English Football League",
    "NBA": "NBA Basketball", "NFL": "NFL Football", "MLB": "MLB Baseball",
    "NHL": "NHL Hockey", "UFC": "UFC / MMA",
}

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap

from metatv.core.database import Database
from metatv.core.models import MediaType
from metatv.gui.epg_agenda_widget import EpgAgendaWidget
from metatv.metadata_providers.base import MetadataResult


def _pref_signal(name: str, weights, attr: str) -> str:
    """Return HTML indicator for a person based on their preference weight."""
    d = getattr(weights, attr, {})
    score = d.get(name, 0.0)
    if score > 0.3:
        return '<span style="color:#4caf50">▲ </span>'
    if score < -0.3:
        return '<span style="color:#f44336">▼ </span>'
    return ''


class DetailsPaneWidget(QWidget):
    """Right-side details pane showing channel metadata
    
    Features:
    - Progressive loading (show cached data immediately, fetch enriched in background)
    - Collapsible sections
    - State persistence (width, visibility, collapsed sections)
    - Image caching for posters/backdrops
    """
    
    # Signals
    play_requested   = pyqtSignal(str)       # channel_id
    favorite_toggled = pyqtSignal(str)       # channel_id
    queue_toggled    = pyqtSignal(str)       # channel_id — add/remove queue
    rating_requested = pyqtSignal(str, int)  # channel_id, ±1

    def __init__(self, config, image_cache, db: Database | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.image_cache = image_cache
        self._db = db
        self.current_channel = None
        self.current_metadata = None
        self.provider_urls = []  # Alternative URLs for image failover
        self._provider_map: dict = {}  # provider_id → {"icon": str, "name": str}
        self._in_queue: bool = False
        self._current_rating: int = 0

        self.setup_ui()
        
        # Connect to image cache signals
        self.image_cache.image_loaded.connect(self._on_image_loaded)
        self.image_cache.image_failed.connect(self._on_image_failed)
    
    def set_provider_urls(self, urls: list):
        """Set provider URLs for image failover"""
        self.provider_urls = urls

    def set_provider_map(self, provider_map: dict):
        """Update the provider icon/name map used in the source badge.

        Args:
            provider_map: Dict mapping provider_id → {"icon": str, "name": str}
        """
        self._provider_map = provider_map
    
    def setup_ui(self):
        """Create the UI layout"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Content widget inside scroll area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        
        # Poster section
        self.create_poster_section()
        
        # Basic info section
        self.create_basic_info_section()
        
        # Plot section
        self.create_plot_section()
        
        # Technical details section (collapsible)
        self.create_technical_section()
        
        # Cast section (collapsible - Phase 2+)
        self.create_cast_section()

        # EPG agenda (live channels only — hidden when no data)
        self._epg_agenda = EpgAgendaWidget(self._db, self.config) if self._db else None
        if self._epg_agenda:
            self.content_layout.addWidget(self._epg_agenda)
            self._epg_agenda.now_title_changed.connect(self._on_epg_title_changed)

        # Add stretch at bottom
        self.content_layout.addStretch()
        
        scroll.setWidget(self.content_widget)
        main_layout.addWidget(scroll)
        
        # Set size constraints
        self.setMinimumWidth(300)
        self.setMaximumWidth(500)
        
        # Restore width from config
        if self.config.details_pane_width:
            self.setFixedWidth(self.config.details_pane_width)
    
    def create_poster_section(self):
        """Create poster image section"""
        self._poster_section = QWidget()
        poster_layout = QVBoxLayout(self._poster_section)
        poster_layout.setContentsMargins(0, 0, 0, 0)

        # Poster label
        self.poster_label = QLabel()
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setMinimumHeight(400)
        self.poster_label.setMaximumHeight(600)
        self.poster_label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.3);
                border-radius: 8px;
            }
        """)
        self.poster_label.setScaledContents(False)  # Keep aspect ratio
        self.poster_label.setText("No poster available")

        poster_layout.addWidget(self.poster_label)

        # Loading indicator (hidden by default)
        self.poster_loading = QLabel("Loading poster...")
        self.poster_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_loading.setStyleSheet("color: gray; font-style: italic;")
        self.poster_loading.hide()
        poster_layout.addWidget(self.poster_loading)

        # Channel icon row for live channels (hidden by default)
        self._live_header = QWidget()
        live_header_layout = QHBoxLayout(self._live_header)
        live_header_layout.setContentsMargins(0, 4, 0, 4)
        live_header_layout.setSpacing(8)
        self._channel_icon_lbl = QLabel()
        self._channel_icon_lbl.setFixedSize(32, 32)
        self._channel_icon_lbl.setScaledContents(True)
        self._channel_icon_lbl.hide()
        live_header_layout.addWidget(self._channel_icon_lbl)

        self._country_info_lbl = QLabel()
        self._country_info_lbl.setStyleSheet("font-size: 11px; color: #777; font-style: italic;")
        self._country_info_lbl.setWordWrap(True)
        self._country_info_lbl.hide()
        live_header_layout.addWidget(self._country_info_lbl, 1)

        self._live_header.hide()

        self.content_layout.addWidget(self._poster_section)
        self.content_layout.addWidget(self._live_header)
    
    def create_basic_info_section(self):
        """Create basic info section (title, year, rating, genres)"""
        # Title
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.content_layout.addWidget(self.title_label)

        # Metadata row (year, rating, runtime) — hidden for live channels
        self._meta_row_widget = QWidget()
        meta_row = QHBoxLayout(self._meta_row_widget)
        meta_row.setContentsMargins(0, 0, 0, 0)

        self.year_label = QLabel()
        self.year_label.setStyleSheet("color: gray;")
        meta_row.addWidget(self.year_label)

        self.rating_label = QLabel()
        self.rating_label.setStyleSheet("color: gold; font-weight: bold;")
        meta_row.addWidget(self.rating_label)

        self.runtime_label = QLabel()
        self.runtime_label.setStyleSheet("color: gray;")
        meta_row.addWidget(self.runtime_label)

        meta_row.addStretch()

        _RATING_BTN_STYLE = """
            QPushButton { border: none; border-radius: 3px; padding: 2px; }
            QPushButton:checked { background: rgba(255,255,255,0.18); }
            QPushButton:hover   { background: rgba(255,255,255,0.10); }
        """
        self.like_button = QPushButton(self.config.like_icon)
        self.like_button.setFixedSize(28, 22)
        self.like_button.setCheckable(True)
        self.like_button.setFlat(True)
        self.like_button.setToolTip("Like")
        self.like_button.setStyleSheet(_RATING_BTN_STYLE)
        self.like_button.clicked.connect(self._on_like_clicked)
        self.like_button.hide()
        meta_row.addWidget(self.like_button)

        self.dislike_button = QPushButton(self.config.dislike_icon)
        self.dislike_button.setFixedSize(28, 22)
        self.dislike_button.setCheckable(True)
        self.dislike_button.setFlat(True)
        self.dislike_button.setToolTip("Dislike")
        self.dislike_button.setStyleSheet(_RATING_BTN_STYLE)
        self.dislike_button.clicked.connect(self._on_dislike_clicked)
        self.dislike_button.hide()
        meta_row.addWidget(self.dislike_button)

        self.content_layout.addWidget(self._meta_row_widget)

        # Source badge (provider name + icon) and adult indicator on the same row
        badge_row = QHBoxLayout()
        self.source_label = QLabel()
        self.source_label.setStyleSheet("color: #888; font-size: 11px;")
        self.source_label.hide()
        badge_row.addWidget(self.source_label)

        self.adult_indicator = QLabel("🔞 Adult")
        self.adult_indicator.setStyleSheet(
            "color: #cc4444; font-size: 11px; font-weight: 600;"
            " background: rgba(204,68,68,0.15); border-radius: 3px; padding: 1px 5px;"
        )
        self.adult_indicator.hide()
        badge_row.addWidget(self.adult_indicator)
        badge_row.addStretch()
        self.content_layout.addLayout(badge_row)

        # Genres — hidden for live channels
        self.genres_label = QLabel()
        self.genres_label.setWordWrap(True)
        self.genres_label.setStyleSheet("color: lightblue;")
        self.content_layout.addWidget(self.genres_label)

        # Recommendation reason — shown only when item selected from a rec surface
        self.rec_reason_label = QLabel()
        self.rec_reason_label.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic;")
        self.rec_reason_label.setWordWrap(True)
        self.rec_reason_label.hide()
        self.content_layout.addWidget(self.rec_reason_label)

        # Action buttons — 3 semantic rows
        self._current_epg_show_title: str = ""

        # Row 1: Watch actions (always visible)
        row1 = QHBoxLayout()
        self.play_button = QPushButton(f"{self.config.play_icon} Play")
        self.play_button.clicked.connect(self._on_play_clicked)
        row1.addWidget(self.play_button, 1)

        self.queue_button = QPushButton(f"{self.config.queue_icon} Add to Queue")
        self.queue_button.clicked.connect(self._on_queue_clicked)
        row1.addWidget(self.queue_button, 1)
        self.content_layout.addLayout(row1)

        # Row 2: Library actions
        row2 = QHBoxLayout()
        self.favorite_button = QPushButton()
        self.favorite_button.clicked.connect(self._on_favorite_clicked)
        row2.addWidget(self.favorite_button, 1)

        self.watchlist_button = QPushButton("+ Watchlist")
        self.watchlist_button.setToolTip("Add current show to watchlist patterns")
        self.watchlist_button.clicked.connect(self._on_watchlist_clicked)
        self.watchlist_button.hide()  # shown only for live channels with EPG data
        row2.addWidget(self.watchlist_button, 1)
        self.content_layout.addLayout(row2)

    
    def create_plot_section(self):
        """Create plot/description section"""
        # Section header
        self._plot_header = QLabel("<b>Overview</b>")
        self.content_layout.addWidget(self._plot_header)
        
        # Plot text
        self.plot_label = QLabel()
        self.plot_label.setWordWrap(True)
        self.plot_label.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_label.setStyleSheet("color: lightgray;")
        self.content_layout.addWidget(self.plot_label)
        
        # Loading indicator
        self.plot_loading = QLabel("Loading description...")
        self.plot_loading.setStyleSheet("color: gray; font-style: italic;")
        self.plot_loading.hide()
        self.content_layout.addWidget(self.plot_loading)
    
    def create_technical_section(self):
        """Create technical details section (collapsible)"""
        # Section header
        self._tech_header = QWidget()
        tech_header_widget = self._tech_header
        tech_header_layout = QHBoxLayout(tech_header_widget)
        tech_header_layout.setContentsMargins(0, 5, 0, 5)
        
        self.tech_toggle_btn = QPushButton(self.config.collapse_icon)
        self.tech_toggle_btn.setFixedSize(20, 20)
        self.tech_toggle_btn.clicked.connect(self._toggle_technical_section)
        tech_header_layout.addWidget(self.tech_toggle_btn)
        
        tech_label = QLabel("<b>Technical Details</b>")
        tech_header_layout.addWidget(tech_label)
        tech_header_layout.addStretch()
        
        self.content_layout.addWidget(tech_header_widget)
        
        # Technical content
        self.tech_content = QWidget()
        tech_content_layout = QVBoxLayout(self.tech_content)
        tech_content_layout.setContentsMargins(20, 0, 0, 0)
        
        self.tech_details_label = QLabel()
        self.tech_details_label.setWordWrap(True)
        self.tech_details_label.setTextFormat(Qt.TextFormat.RichText)
        self.tech_details_label.setStyleSheet("color: lightgray;")
        tech_content_layout.addWidget(self.tech_details_label)
        
        self.content_layout.addWidget(self.tech_content)
        
        # Restore collapsed state
        if "technical" in self.config.details_pane_collapsed_sections:
            self.tech_content.hide()
            self.tech_toggle_btn.setText(self.config.expand_icon)
    
    def create_cast_section(self):
        """Create cast section (collapsible) - Phase 2+"""
        # Section header
        self._cast_header = QWidget()
        cast_header_widget = self._cast_header
        cast_header_layout = QHBoxLayout(cast_header_widget)
        cast_header_layout.setContentsMargins(0, 5, 0, 5)
        
        self.cast_toggle_btn = QPushButton(self.config.collapse_icon)
        self.cast_toggle_btn.setFixedSize(20, 20)
        self.cast_toggle_btn.clicked.connect(self._toggle_cast_section)
        cast_header_layout.addWidget(self.cast_toggle_btn)
        
        cast_label = QLabel("<b>Cast & Crew</b>")
        cast_header_layout.addWidget(cast_label)
        cast_header_layout.addStretch()
        
        self.content_layout.addWidget(cast_header_widget)
        
        # Cast content
        self.cast_content = QWidget()
        cast_content_layout = QVBoxLayout(self.cast_content)
        cast_content_layout.setContentsMargins(20, 0, 0, 0)
        
        self.cast_label = QLabel()
        self.cast_label.setWordWrap(True)
        self.cast_label.setTextFormat(Qt.TextFormat.RichText)
        self.cast_label.setStyleSheet("color: lightgray;")
        cast_content_layout.addWidget(self.cast_label)
        
        self.content_layout.addWidget(self.cast_content)
        
        # Restore collapsed state
        if "cast" in self.config.details_pane_collapsed_sections:
            self.cast_content.hide()
            self.cast_toggle_btn.setText(self.config.expand_icon)
    
    def show_channel(self, channel, metadata: Optional[MetadataResult] = None):
        """Display metadata for a channel

        Args:
            channel: Channel object from database
            metadata: Optional MetadataResult (if None, will show basic info only)
        """
        logger.debug(f"show_channel called for {channel.name}, metadata={metadata is not None}")
        self.current_channel = channel
        self.current_metadata = metadata
        is_live = getattr(channel, "media_type", None) == MediaType.LIVE

        # Configure layout for channel type (before clearing so flicker is minimised)
        self._configure_for_live(is_live)

        # Clear previous state (also clears rec reason label)
        self._clear_display()

        # Load queue/rating state for action buttons
        self._load_action_state(channel.id)

        # Country/category info for live channels (after clear so it isn't hidden again)
        if is_live:
            self._update_country_info(channel.name)

        # Show basic channel info immediately (Tier 1 - instant)
        self._show_basic_channel_info(channel)

        # Channel icon for live channels (async)
        if is_live:
            logo = getattr(channel, "logo_url", None)
            if logo:
                pix = self.image_cache.get_image_sync(logo)
                if pix:
                    self._channel_icon_lbl.setPixmap(pix)
                    self._channel_icon_lbl.show()
                else:
                    self._channel_icon_lbl.hide()
                    self.image_cache.get_image_async(logo)
            else:
                self._channel_icon_lbl.hide()

        # EPG agenda — only for live channels
        if self._epg_agenda:
            if is_live:
                self._epg_agenda.load_for_channel(channel.id)
            else:
                self._epg_agenda.clear()

        # If we have metadata, display it (Tier 2/3 - progressive)
        if metadata:
            logger.debug(f"Calling _show_metadata for {channel.name}")
            self._show_metadata(metadata)
        elif not is_live:
            logger.debug(f"Showing loading state for {channel.name}")
            self._show_loading_state()
    
    def _update_country_info(self, channel_name: str) -> None:
        """Extract and display category/country prefix from channel name."""
        m = _CHANNEL_PREFIX_RE.match(channel_name)
        if not m:
            self._country_info_lbl.setText("Category: unknown  ·  no prefix detected")
            self._country_info_lbl.show()
            return
        raw = m.group(1)
        delimiter = "★" if m.group(2) == "★" else "|"
        code = _COUNTRY_ABBREV_DP.get(raw, raw)
        full = _CATEGORY_FULL_NAMES_DP.get(code, "")
        if full:
            text = f"Category: {full} ({code})  ·  via {delimiter} prefix"
        else:
            text = f"Category: {code}  ·  via {delimiter} prefix (unrecognized)"
        self._country_info_lbl.setText(text)
        self._country_info_lbl.show()

    def _clear_display(self):
        """Clear all displayed content"""
        self.poster_label.clear()
        # Don't set "No poster available" yet - wait until we've tried to load it
        self.title_label.clear()
        self.year_label.clear()
        self.rating_label.clear()
        self.runtime_label.clear()
        self.genres_label.clear()
        self.plot_label.clear()
        self.tech_details_label.clear()
        self.cast_label.clear()
        self.source_label.clear()
        self.source_label.hide()
        self.adult_indicator.hide()
        self._country_info_lbl.hide()
        self.rec_reason_label.hide()

        self.poster_loading.hide()
        self.plot_loading.hide()

    def _configure_for_live(self, is_live: bool) -> None:
        """Show/hide sections depending on whether the selected channel is live TV."""
        # Sections only relevant for VOD (movies, series)
        for widget in (
            self._poster_section,
            self._meta_row_widget,
            self.genres_label,
            self._plot_header,
            self.plot_label,
            self.plot_loading,
            self._tech_header,
            self.tech_content,
            self._cast_header,
            self.cast_content,
        ):
            widget.setVisible(not is_live)

        # Live-only elements
        self._live_header.setVisible(is_live)
        self.watchlist_button.setVisible(is_live)

        # Like/Dislike only for movies/series
        self.like_button.setVisible(not is_live)
        self.dislike_button.setVisible(not is_live)

        # Title font: larger for live since it's the channel name without other context
        if is_live:
            self.title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        else:
            self.title_label.setStyleSheet("font-size: 18px; font-weight: bold;")

    def _on_epg_title_changed(self, title: str) -> None:
        """Called when the EPG agenda loads the current show title."""
        self._current_epg_show_title = title
        if title:
            already = title in (self.config.epg_watchlist_patterns or [])
            self.watchlist_button.setText(f"{self.config.watched_icon} On Watchlist" if already else "+ Watchlist")
        else:
            self.watchlist_button.setText("+ Watchlist")

    def _on_watchlist_clicked(self) -> None:
        title = self._current_epg_show_title
        if not title:
            return
        patterns = list(self.config.epg_watchlist_patterns or [])
        if title in patterns:
            patterns.remove(title)
            self.watchlist_button.setText("+ Watchlist")
        else:
            patterns.append(title)
            self.watchlist_button.setText("✓ On Watchlist")
        self.config.epg_watchlist_patterns = patterns
        self.config.save()

    def _show_basic_channel_info(self, channel):
        """Show basic channel info (immediate - Tier 1)"""
        # Title
        self.title_label.setText(channel.name)
        
        # Update favorite button
        if channel.is_favorite:
            self.favorite_button.setText(f"{self.config.favorite_icon} Favorited")
        else:
            self.favorite_button.setText(f"{self.config.unfavorite_icon} Add to Favorites")
        
        # Media type indicator
        media_icon = {
            "live": self.config.live_icon,
            "movie": self.config.movie_icon,
            "series": self.config.series_icon,
        }.get(channel.media_type, self.config.unknown_icon)

        self.year_label.setText(f"{media_icon} {channel.media_type.title()}")

        # Source badge
        provider_info = self._provider_map.get(getattr(channel, 'provider_id', None))
        if provider_info:
            icon = provider_info.get('icon', '')
            name = provider_info.get('name', '')
            badge = f"{icon} {name}".strip() if icon else name
            if badge:
                self.source_label.setText(f"Source: {badge}")
                self.source_label.show()

        # Adult content indicator
        if getattr(channel, 'is_adult', False):
            self.adult_indicator.show()
        else:
            self.adult_indicator.hide()
    
    def _show_loading_state(self):
        """Show loading indicators for sections being fetched"""
        self.poster_loading.show()
        self.poster_loading.setText(f"{self.config.loading_icon} Loading poster...")
        
        self.plot_loading.show()
        self.plot_loading.setText(f"{self.config.loading_icon} Loading metadata...")
    
    def _show_metadata(self, metadata: MetadataResult):
        """Show metadata (Tier 2/3 - progressive)"""
        logger.debug(f"Displaying metadata: title={metadata.title}, plot={bool(metadata.plot)}, cast={len(metadata.cast) if metadata.cast else 0}")
        
        # Title (prefer metadata title over channel name)
        if metadata.title:
            self.title_label.setText(metadata.title)
        
        # Year
        if metadata.year:
            self.year_label.setText(f"{metadata.year}")
        
        # Rating
        if metadata.rating:
            stars = self.config.rating_star_icon * int(metadata.rating / 2)  # Convert 0-10 to 0-5 stars
            self.rating_label.setText(f"{stars} {metadata.rating:.1f}/10")
        
        # Runtime
        if metadata.runtime:
            hours = metadata.runtime // 60
            minutes = metadata.runtime % 60
            if hours > 0:
                self.runtime_label.setText(f"{hours}h {minutes}m")
            else:
                self.runtime_label.setText(f"{minutes}m")
        
        # Genres
        if metadata.genres:
            self.genres_label.setText(" • ".join(metadata.genres))
            logger.debug(f"Genres: {metadata.genres}")
        
        # Plot
        if metadata.plot:
            self.plot_label.setText(metadata.plot)
            self.plot_loading.hide()
            logger.debug(f"Plot length: {len(metadata.plot)} chars")
        else:
            logger.debug("No plot available")
        
        # Poster (async load)
        if metadata.poster_url:
            logger.debug(f"Loading poster from: {metadata.poster_url}")
            # Show loading indicator
            self.poster_loading.show()
            self.poster_loading.setText(f"{self.config.loading_icon} Loading poster...")
            
            # Try sync first (cached)
            pixmap = self.image_cache.get_image_sync(metadata.poster_url)
            if pixmap:
                self._display_poster(pixmap)
                self.poster_loading.hide()
            else:
                # Request async download with provider URL failover
                self.image_cache.get_image_async(metadata.poster_url, self.provider_urls)
        else:
            self.poster_loading.hide()
            self.poster_label.setText("No poster available")
            logger.debug("No poster URL available")
        
        # Load preference weights once for director/cast annotation
        _weights = None
        if self._db:
            from metatv.core.preference_engine import compute_weights
            _wt_sess = self._db.get_session()
            try:
                _w = compute_weights(_wt_sess)
                _weights = None if _w.is_empty() else _w
            except Exception:
                pass
            finally:
                _wt_sess.close()

        # Technical details
        tech_parts = []
        if metadata.release_date:
            tech_parts.append(f"<b>Release Date:</b> {metadata.release_date}")
        if metadata.content_rating:
            tech_parts.append(f"<b>Content Rating:</b> {metadata.content_rating}")
        if metadata.director:
            if _weights:
                from metatv.core.preference_engine import _split_directors
                dir_parts = [
                    f"{_pref_signal(d, _weights, 'directors')}{d}"
                    for d in _split_directors(metadata.director)
                ]
                dir_str = ", ".join(dir_parts)
            else:
                dir_str = metadata.director
            tech_parts.append(f"<b>Director:</b> {dir_str}")
        if metadata.tmdb_id:
            tech_parts.append(f"<b>TMDb ID:</b> {metadata.tmdb_id}")

        if tech_parts:
            self.tech_details_label.setText("<br>".join(tech_parts))
            logger.debug(f"Technical details: {len(tech_parts)} fields")
        else:
            logger.debug("No technical details available")

        # Cast — annotate with preference signals if weights available
        if metadata.cast:
            parts = []
            for actor in metadata.cast[:10]:
                name = actor.get('name', 'Unknown') if isinstance(actor, dict) else str(actor)
                sig = _pref_signal(name, _weights, 'actors') if _weights else ''
                parts.append(f"{sig}{name}")
            if parts:
                self.cast_label.setText(", ".join(parts))
                logger.debug(f"Cast: {len(parts)} actors")
        else:
            logger.debug("No cast available")
    
    def _display_poster(self, pixmap: QPixmap):
        """Display poster image with proper scaling"""
        if pixmap and not pixmap.isNull():
            # Scale to fit label while maintaining aspect ratio
            scaled = pixmap.scaled(
                self.poster_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.poster_label.setPixmap(scaled)
        else:
            self.poster_label.setText("No poster available")
    
    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """Handle image loaded from cache"""
        # Poster for VOD channels
        if self.current_metadata and self.current_metadata.poster_url == url:
            self._display_poster(pixmap)
            self.poster_loading.hide()
        # Channel icon for live channels
        logo = getattr(self.current_channel, "logo_url", None) if self.current_channel else None
        if logo and logo == url and not pixmap.isNull():
            self._channel_icon_lbl.setPixmap(pixmap)
            self._channel_icon_lbl.show()
    
    def _on_image_failed(self, url: str, error: str):
        """Handle image load failure"""
        if self.current_metadata and self.current_metadata.poster_url == url:
            self.poster_label.setText("Failed to load poster")
            self.poster_loading.hide()
            logger.debug(f"Failed to load poster: {error}")
    
    def _toggle_technical_section(self):
        """Toggle technical details section"""
        is_visible = self.tech_content.isVisible()
        self.tech_content.setVisible(not is_visible)
        
        if is_visible:
            self.tech_toggle_btn.setText(self.config.expand_icon)
            if "technical" not in self.config.details_pane_collapsed_sections:
                self.config.details_pane_collapsed_sections.append("technical")
        else:
            self.tech_toggle_btn.setText(self.config.collapse_icon)
            if "technical" in self.config.details_pane_collapsed_sections:
                self.config.details_pane_collapsed_sections.remove("technical")
        
        self.config.save()
    
    def _toggle_cast_section(self):
        """Toggle cast section"""
        is_visible = self.cast_content.isVisible()
        self.cast_content.setVisible(not is_visible)
        
        if is_visible:
            self.cast_toggle_btn.setText(self.config.expand_icon)
            if "cast" not in self.config.details_pane_collapsed_sections:
                self.config.details_pane_collapsed_sections.append("cast")
        else:
            self.cast_toggle_btn.setText(self.config.collapse_icon)
            if "cast" in self.config.details_pane_collapsed_sections:
                self.config.details_pane_collapsed_sections.remove("cast")
        
        self.config.save()
    
    def _on_play_clicked(self):
        """Handle play button click"""
        if self.current_channel:
            self.play_requested.emit(self.current_channel.id)
    
    def _on_favorite_clicked(self):
        """Handle favorite button click"""
        if self.current_channel:
            self.favorite_toggled.emit(self.current_channel.id)

    def _on_queue_clicked(self):
        if self.current_channel:
            self._in_queue = not self._in_queue
            self._update_action_buttons()
            self.queue_toggled.emit(self.current_channel.id)

    def _on_like_clicked(self):
        if self.current_channel:
            new_rating = 0 if self._current_rating == 1 else 1
            self._current_rating = new_rating
            self._update_action_buttons()
            self.rating_requested.emit(self.current_channel.id, 1)

    def _on_dislike_clicked(self):
        if self.current_channel:
            new_rating = 0 if self._current_rating == -1 else -1
            self._current_rating = new_rating
            self._update_action_buttons()
            self.rating_requested.emit(self.current_channel.id, -1)

    def _load_action_state(self, channel_id: str) -> None:
        """Query DB for queue and rating state, then update button display."""
        self._in_queue = False
        self._current_rating = 0
        if self._db:
            from metatv.core.repositories import RepositoryFactory
            session = self._db.get_session()
            try:
                repos = RepositoryFactory(session)
                self._in_queue = repos.queue.is_queued(channel_id)
                self._current_rating = repos.ratings.get(channel_id) or 0
            finally:
                session.close()
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        """Refresh button labels and checked states from cached _in_queue / _current_rating."""
        self.queue_button.setText(
            f"{self.config.queue_icon} Remove from Queue" if self._in_queue
            else f"{self.config.queue_icon} Add to Queue"
        )
        self.like_button.setChecked(self._current_rating == 1)
        self.dislike_button.setChecked(self._current_rating == -1)

    def set_recommendation_reason(self, reason: str | None) -> None:
        """Show or hide the 'Recommended because …' label."""
        if reason:
            self.rec_reason_label.setText(f"{self.config.preferences_icon} Recommended: {reason}")
            self.rec_reason_label.show()
        else:
            self.rec_reason_label.hide()
