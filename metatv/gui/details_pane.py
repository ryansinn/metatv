"""Details pane widget - shows metadata for selected channel"""
from typing import Optional

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap

from metatv.metadata_providers.base import MetadataResult


class DetailsPaneWidget(QWidget):
    """Right-side details pane showing channel metadata
    
    Features:
    - Progressive loading (show cached data immediately, fetch enriched in background)
    - Collapsible sections
    - State persistence (width, visibility, collapsed sections)
    - Image caching for posters/backdrops
    """
    
    # Signals
    play_requested = pyqtSignal(str)  # channel_id
    favorite_toggled = pyqtSignal(str)  # channel_id
    
    def __init__(self, config, image_cache, parent=None):
        super().__init__(parent)
        self.config = config
        self.image_cache = image_cache
        self.current_channel = None
        self.current_metadata = None
        self.provider_urls = []  # Alternative URLs for image failover
        
        self.setup_ui()
        
        # Connect to image cache signals
        self.image_cache.image_loaded.connect(self._on_image_loaded)
        self.image_cache.image_failed.connect(self._on_image_failed)
    
    def set_provider_urls(self, urls: list):
        """Set provider URLs for image failover"""
        self.provider_urls = urls
    
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
        poster_container = QWidget()
        poster_layout = QVBoxLayout(poster_container)
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
        
        self.content_layout.addWidget(poster_container)
    
    def create_basic_info_section(self):
        """Create basic info section (title, year, rating, genres)"""
        # Title
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.content_layout.addWidget(self.title_label)
        
        # Metadata row (year, rating, runtime)
        meta_row = QHBoxLayout()
        
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
        self.content_layout.addLayout(meta_row)
        
        # Genres
        self.genres_label = QLabel()
        self.genres_label.setWordWrap(True)
        self.genres_label.setStyleSheet("color: lightblue;")
        self.content_layout.addWidget(self.genres_label)
        
        # Action buttons
        buttons_layout = QHBoxLayout()
        
        self.play_button = QPushButton(f"{self.config.play_icon} Play")
        self.play_button.clicked.connect(self._on_play_clicked)
        buttons_layout.addWidget(self.play_button)
        
        self.favorite_button = QPushButton()
        self.favorite_button.clicked.connect(self._on_favorite_clicked)
        buttons_layout.addWidget(self.favorite_button)
        
        self.content_layout.addLayout(buttons_layout)
    
    def create_plot_section(self):
        """Create plot/description section"""
        # Section header
        plot_header = QLabel("<b>Overview</b>")
        self.content_layout.addWidget(plot_header)
        
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
        tech_header_widget = QWidget()
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
        cast_header_widget = QWidget()
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
        
        # Clear previous state
        self._clear_display()
        
        # Show basic channel info immediately (Tier 1 - instant)
        self._show_basic_channel_info(channel)
        
        # If we have metadata, display it (Tier 2/3 - progressive)
        if metadata:
            logger.debug(f"Calling _show_metadata for {channel.name}")
            self._show_metadata(metadata)
        else:
            # Show loading indicators
            logger.debug(f"Showing loading state for {channel.name}")
            self._show_loading_state()
    
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
        
        self.poster_loading.hide()
        self.plot_loading.hide()
    
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
            stars = "★" * int(metadata.rating / 2)  # Convert 0-10 to 0-5 stars
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
        
        # Technical details
        tech_parts = []
        if metadata.release_date:
            tech_parts.append(f"<b>Release Date:</b> {metadata.release_date}")
        if metadata.content_rating:
            tech_parts.append(f"<b>Rating:</b> {metadata.content_rating}")
        if metadata.director:
            tech_parts.append(f"<b>Director:</b> {metadata.director}")
        if metadata.tmdb_id:
            tech_parts.append(f"<b>TMDb ID:</b> {metadata.tmdb_id}")
        
        if tech_parts:
            self.tech_details_label.setText("<br>".join(tech_parts))
            logger.debug(f"Technical details: {len(tech_parts)} fields")
        else:
            logger.debug("No technical details available")
        
        # Cast
        if metadata.cast:
            cast_names = [actor.get('name', 'Unknown') for actor in metadata.cast[:10]]  # First 10
            if cast_names:
                self.cast_label.setText(", ".join(cast_names))
                logger.debug(f"Cast: {len(cast_names)} actors")
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
        # Check if this is for the current channel
        if self.current_metadata and self.current_metadata.poster_url == url:
            self._display_poster(pixmap)
            self.poster_loading.hide()
    
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
