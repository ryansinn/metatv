"""Content section widgets for the details pane: poster, metadata, plot, technical, cast."""
import html
import re

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.channel_name_utils import (
    normalize_region_code, REGION_FULL_NAMES, QUALITY_TOKENS, parse_channel_name,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_versions import _CHANNEL_PREFIX_RE, resolve_category_name, _FlowLayout
from metatv.metadata_providers.base import MetadataResult


class _ClickableLabel(QLabel):
    """QLabel that copies its stored channel_id to clipboard on click."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channel_id = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if self.channel_id and event.button() == Qt.MouseButton.LeftButton:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.channel_id)
            self.clicked.emit()
        super().mousePressEvent(event)


class _PosterLabel(QLabel):
    """QLabel that emits ``poster_clicked`` when the user left-clicks a loaded poster."""

    poster_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_pixmap: bool = False

    def setPixmap(self, pixmap: QPixmap) -> None:  # type: ignore[override]
        super().setPixmap(pixmap)
        self._has_pixmap = not (pixmap is None or pixmap.isNull())
        self._update_cursor()

    def clear(self) -> None:
        super().clear()
        self._has_pixmap = False
        self._update_cursor()

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        # Clearing the image via text also clears the pixmap state
        self._has_pixmap = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._has_pixmap:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event) -> None:
        if self._has_pixmap and event.button() == Qt.MouseButton.LeftButton:
            self.poster_clicked.emit()
        super().mousePressEvent(event)


def _pref_signal(name: str, weights, attr: str) -> str:
    """Return HTML indicator for a person based on their preference weight."""
    d = getattr(weights, attr, {})
    score = d.get(name, 0.0)
    if score > 0.3:
        return f'<span style="color:{_theme.COLOR_OK}">▲ </span>'
    if score < -0.3:
        return f'<span style="color:{_theme.COLOR_ERR}">▼ </span>'
    return ''


# ---------------------------------------------------------------------------
# _PosterSection
# ---------------------------------------------------------------------------

class _PosterSection(QWidget):
    """Poster image (VOD) and live-channel header (icon + country info)."""

    # Emitted when the user clicks an enlarged poster (carries the full-res QPixmap)
    poster_enlarged = pyqtSignal(QPixmap)

    def __init__(self, config, image_cache, parent=None):
        super().__init__(parent)
        self.config = config
        self._image_cache = image_cache
        self._poster_url: str | None = None
        self._logo_url: str | None = None
        self._provider_urls: list = []
        self._full_pixmap: QPixmap | None = None   # full-res image for the lightbox
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Poster + sentiment-rail wrapper (VOD only).
        # The left column (_sentiment_rail) holds the 👍/🚫/👎 buttons as a
        # vertical bordered-chip rail; the poster fills the remaining space.
        # Buttons are reparented into the rail via set_sentiment_buttons() after
        # both _PosterSection and _ActionBar have been constructed.
        _poster_and_rail = QWidget()
        _par_layout = QHBoxLayout(_poster_and_rail)
        _par_layout.setContentsMargins(0, 0, 0, 0)
        _par_layout.setSpacing(0)

        self._sentiment_rail = QWidget()
        self._sentiment_rail.setFixedWidth(42)
        self._sentiment_rail_layout = QVBoxLayout(self._sentiment_rail)
        self._sentiment_rail_layout.setContentsMargins(0, 4, 4, 4)
        self._sentiment_rail_layout.setSpacing(6)
        self._sentiment_rail_layout.addStretch()
        self._sentiment_rail_layout.addStretch()   # placeholder; buttons go between stretches
        self._sentiment_rail.hide()   # shown only after set_sentiment_buttons() + set_mode(VOD)
        _par_layout.addWidget(self._sentiment_rail)

        # Poster label (VOD)
        self._poster_frame = QWidget()
        pf_layout = QVBoxLayout(self._poster_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)

        self.poster_label = _PosterLabel()
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setMinimumHeight(400)
        self.poster_label.setMaximumHeight(600)
        self.poster_label.setStyleSheet(
            f"QLabel {{ background-color: {_theme.OVERLAY_BLACK_30}; border-radius: 8px;"
            f" color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM}; }}"
        )
        self.poster_label.setScaledContents(False)
        self.poster_label.setText("No poster available")
        self.poster_label.setToolTip(f"{_icons.zoom_poster_icon} Click to enlarge")
        self.poster_label.poster_clicked.connect(self._on_poster_clicked)
        pf_layout.addWidget(self.poster_label)

        _par_layout.addWidget(self._poster_frame, 1)
        layout.addWidget(_poster_and_rail)

        # Live header: channel icon + country info
        self._live_header = QWidget()
        live_layout = QHBoxLayout(self._live_header)
        live_layout.setContentsMargins(0, 4, 0, 4)
        live_layout.setSpacing(8)

        self._channel_icon_lbl = QLabel()
        self._channel_icon_lbl.setFixedSize(32, 32)
        self._channel_icon_lbl.setScaledContents(True)
        self._channel_icon_lbl.hide()
        live_layout.addWidget(self._channel_icon_lbl)

        self._country_info_lbl = QLabel()
        self._country_info_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_DISABLED}; font-style: italic;")
        self._country_info_lbl.setWordWrap(True)
        self._country_info_lbl.hide()
        live_layout.addWidget(self._country_info_lbl, 1)

        self._live_header.hide()
        layout.addWidget(self._live_header)

    def set_mode(self, is_live: bool) -> None:
        self._poster_frame.setVisible(not is_live)
        # Sentiment rail follows the poster — both hidden for live channels.
        # Individual button visibility is managed by _ActionBar.set_mode(); this
        # just controls whether the rail container itself appears.
        self._sentiment_rail.setVisible(not is_live)
        self._live_header.setVisible(is_live)

    def set_sentiment_buttons(self, like_btn, not_interested_btn, dislike_btn) -> None:
        """Reparent the three sentiment buttons into the left-rail vertical stack.

        Called once from details_pane._setup_ui() after both _PosterSection and
        _ActionBar have been constructed.  The buttons are owned by _ActionBar
        (signals/state/sync live there); we just reparent them into this visual slot.
        """
        # Clear the two placeholder stretches, then rebuild: stretch → btns → stretch
        while self._sentiment_rail_layout.count():
            self._sentiment_rail_layout.takeAt(0)
        self._sentiment_rail_layout.addStretch()
        for btn in (like_btn, not_interested_btn, dislike_btn):
            self._sentiment_rail_layout.addWidget(btn)
        self._sentiment_rail_layout.addStretch()

    def set_provider_urls(self, urls: list) -> None:
        self._provider_urls = urls

    def load_poster(self, url: str, provider_urls: list | None = None) -> None:
        """Start loading a poster URL (sync-first, async fallback)."""
        if provider_urls is not None:
            self._provider_urls = provider_urls
        self._poster_url = url
        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText(f"{_icons.loading_icon} Loading poster...")
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._display_poster(pix)
        else:
            self._image_cache.get_image_async(url, self._provider_urls)

    def load_logo(self, url: str) -> None:
        """Load channel icon for live header (sync-first, async fallback)."""
        self._logo_url = url
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._channel_icon_lbl.setPixmap(pix)
            self._channel_icon_lbl.show()
        else:
            self._channel_icon_lbl.hide()
            self._image_cache.get_image_async(url)

    def set_country_info(self, channel_name: str) -> None:
        """Extract and display category/country prefix from a channel name."""
        m = _CHANNEL_PREFIX_RE.match(channel_name)
        if not m:
            self._country_info_lbl.setText("Category: unknown  ·  no prefix detected")
            self._country_info_lbl.show()
            return
        raw = m.group(1)
        delimiter = "★" if m.group(2) == "★" else "|"
        code = normalize_region_code(raw)
        full = REGION_FULL_NAMES.get(code, "")
        text = (
            f"Category: {full} ({code})  ·  via {delimiter} prefix"
            if full
            else f"Category: {code}  ·  via {delimiter} prefix (unrecognized)"
        )
        self._country_info_lbl.setText(text)
        self._country_info_lbl.show()

    def on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url == self._poster_url and not pixmap.isNull():
            self._display_poster(pixmap)
        if url == self._logo_url and not pixmap.isNull():
            self._channel_icon_lbl.setPixmap(pixmap)
            self._channel_icon_lbl.show()

    def on_image_failed(self, url: str, error: str) -> None:
        if url == self._poster_url:
            self.poster_label.setText("Failed to load poster")
            logger.debug(f"Poster load failed: {error}")

    def clear(self) -> None:
        self._poster_url = None
        self._logo_url = None
        self._full_pixmap = None
        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText("No poster available")
        self._country_info_lbl.hide()
        self._channel_icon_lbl.hide()

    def _display_poster(self, pixmap: QPixmap) -> None:
        if pixmap and not pixmap.isNull():
            self._full_pixmap = pixmap   # retain original for lightbox enlargement
            scaled = pixmap.scaled(
                self.poster_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.poster_label.setPixmap(scaled)
        else:
            self.poster_label.setText("No poster available")

    def _on_poster_clicked(self) -> None:
        """Emit poster_enlarged with the full-res pixmap when the poster is clicked."""
        if self._full_pixmap and not self._full_pixmap.isNull():
            self.poster_enlarged.emit(self._full_pixmap)


# ---------------------------------------------------------------------------
# _MetadataSection
# ---------------------------------------------------------------------------

class _MetadataSection(QWidget):
    """Title, year, rating, genres, source badge, adult indicator, rec reason."""

    genre_clicked = pyqtSignal(str)  # emits the genre name when user clicks a genre chip

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Title bar: [title ···] [chip] [year]
        title_bar = QWidget()
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)
        title_bar_layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setStyleSheet(_theme.DETAIL_TITLE)
        title_bar_layout.addWidget(self.title_label, 1)

        self._prefix_chip = QPushButton()
        self._prefix_chip.setFlat(True)
        self._prefix_chip.setStyleSheet(_theme.CATEGORY_CHIP)
        self._prefix_chip.setFixedHeight(24)
        self._prefix_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._prefix_chip.hide()
        title_bar_layout.addWidget(self._prefix_chip)

        self._quality_chip = QPushButton()
        self._quality_chip.setFlat(True)
        self._quality_chip.setStyleSheet(_theme.QUALITY_CHIP)
        self._quality_chip.setFixedHeight(24)
        self._quality_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._quality_chip.hide()
        title_bar_layout.addWidget(self._quality_chip)

        self._name_year_lbl = QLabel()
        self._name_year_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_MUTED}; font-weight: bold;"
        )
        self._name_year_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._name_year_lbl.hide()
        title_bar_layout.addWidget(self._name_year_lbl)

        layout.addWidget(title_bar)

        # Tagline — italic subtitle line, shown when metadata provides it
        self._tagline_lbl = QLabel()
        self._tagline_lbl.setWordWrap(True)
        self._tagline_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-style: italic; font-size: {_theme.FONT_LG};"
        )
        self._tagline_lbl.hide()
        layout.addWidget(self._tagline_lbl)

        # Media type row: [icon Type] [runtime] stretch [IMDb xxx] [TMDb xxx] [PG-13] [★★★ X of 10]
        # Rating and content-rating badge sit right-aligned on this row — the right side
        # is otherwise empty for most channels, so this reclaims wasted vertical space.
        self._media_row = QWidget()
        media_row_layout = QHBoxLayout(self._media_row)
        media_row_layout.setContentsMargins(0, 0, 0, 0)
        media_row_layout.setSpacing(8)

        self._media_type_lbl = QLabel()
        self._media_type_lbl.setStyleSheet(_theme.META_DIM)
        media_row_layout.addWidget(self._media_type_lbl)

        self.runtime_label = QLabel()
        self.runtime_label.setStyleSheet(_theme.META_DIM)
        self.runtime_label.hide()
        media_row_layout.addWidget(self.runtime_label)

        media_row_layout.addStretch()

        self._imdb_lbl = QLabel()
        self._imdb_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM};"
        )
        self._imdb_lbl.hide()
        media_row_layout.addWidget(self._imdb_lbl)

        self._tmdb_lbl = QLabel()
        self._tmdb_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM};"
        )
        self._tmdb_lbl.hide()
        media_row_layout.addWidget(self._tmdb_lbl)

        # PG-13 / content-rating badge — right of the IDs, left of the stars
        self._content_rating_lbl = QLabel()
        self._content_rating_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM};"
            f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 3px; padding: 1px 4px;"
        )
        self._content_rating_lbl.hide()
        media_row_layout.addWidget(self._content_rating_lbl)

        # Star rating — rightmost, hidden when no rating present (no empty gap)
        self.rating_label = QLabel()
        self.rating_label.setStyleSheet(f"color: {_theme.COLOR_GOLD}; font-weight: bold;")
        self.rating_label.hide()
        media_row_layout.addWidget(self.rating_label)

        layout.addWidget(self._media_row)

        # Source badge + adult indicator row
        badge_row = QHBoxLayout()
        self.source_label = _ClickableLabel()
        self.source_label.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
        self.source_label.hide()
        badge_row.addWidget(self.source_label)
        self.adult_indicator = QLabel("🔞 Adult")
        self.adult_indicator.setStyleSheet(
            f"color: {_theme.COLOR_ERR_2}; font-size: {_theme.FONT_MD}; font-weight: 600;"
            f" background: {_theme.OVERLAY_ERR2_15}; border-radius: 3px; padding: 1px 5px;"
        )
        self.adult_indicator.hide()
        badge_row.addWidget(self.adult_indicator)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        # Genres — flow-layout row of clickable chip buttons; wraps cleanly at panel width.
        # _genres_loading_lbl is shown while metadata is loading; _genres_container replaces
        # it once genres arrive.  Both start hidden; load_basic() shows the loading label;
        # load_metadata() hides it and populates the flow container.
        self._genres_loading_lbl = QLabel()
        self._genres_loading_lbl.setStyleSheet(
            f"color: {_theme.COLOR_DIM}; font-size: {_theme.FONT_MD};"
        )
        self._genres_loading_lbl.hide()
        layout.addWidget(self._genres_loading_lbl)

        self._genres_container = QWidget()
        self._genres_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self._genres_layout = _FlowLayout(self._genres_container, h_spacing=4, v_spacing=4)
        self._genres_container.hide()
        layout.addWidget(self._genres_container)

        # Watch-completion status (VOD only) — "✓ Watched" or "Resume at M:SS"
        self._watch_status_lbl = QLabel()
        self._watch_status_lbl.setStyleSheet(_theme.WATCH_STATUS_DONE)
        self._watch_status_lbl.hide()
        layout.addWidget(self._watch_status_lbl)

        # Recommendation reason
        self.rec_reason_label = QLabel()
        self.rec_reason_label.setStyleSheet(f"color: {_theme.COLOR_DIM}; font-size: {_theme.FONT_MD}; font-style: italic;")
        self.rec_reason_label.setWordWrap(True)
        self.rec_reason_label.hide()
        layout.addWidget(self.rec_reason_label)

    def set_mode(self, is_live: bool) -> None:
        self._media_row.setVisible(not is_live)
        if is_live:
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
        if is_live:
            self.title_label.setStyleSheet(f"font-size: {_theme.FONT_4XL}; font-weight: bold;")
            self._tagline_lbl.hide()
            # rating_label and _content_rating_lbl live on _media_row which is
            # already hidden above via self._media_row.setVisible(not is_live)
        else:
            self.title_label.setStyleSheet(_theme.DETAIL_TITLE)

    def load_basic(self, channel, provider_map: dict | None = None) -> None:
        """Tier-1 display: channel attributes only, no metadata.

        Reads stored detected_* fields written at ingestion time — never calls
        parse_channel_name() here (ingestion-only rule, CLAUDE.md).
        """
        # Title — use stored detected_title (prefix/suffix already stripped at ingestion).
        clean_title = getattr(channel, "detected_title", None) or channel.name
        self.title_label.setText(clean_title)
        self.title_label.setToolTip(channel.name)

        # Prefix chip — shows detected category code (EN, NF, D+, etc.).
        # Quality tokens (4K, HD, etc.) are not region/platform chips; skip them.
        # Priority: detected_prefix (separator prefix) > detected_region (parenthetical origin)
        prefix = (
            getattr(channel, "detected_prefix", None)
            or getattr(channel, "detected_region", None)
            or ""
        )
        if prefix and prefix.upper() not in QUALITY_TOKENS:
            tip = resolve_category_name(prefix, self.config) or prefix
            self._prefix_chip.setText(prefix)
            self._prefix_chip.setToolTip(tip)
            self._prefix_chip.show()
        else:
            self._prefix_chip.hide()

        # Quality chip — shows detected quality (4K, UHD, HD, etc.) next to language chip.
        quality = getattr(channel, "detected_quality", None)
        if quality:
            self._quality_chip.setText(quality.upper())
            self._quality_chip.setToolTip(f"{quality.upper()} quality")
            self._quality_chip.show()
        else:
            self._quality_chip.hide()

        # Year from channel name — shown to the right of the title
        year = getattr(channel, "detected_year", None)
        if year:
            self._name_year_lbl.setText(year)
            self._name_year_lbl.show()
        else:
            self._name_year_lbl.hide()

        media_icon = {
            "live":   _icons.live_icon,
            "movie":  _icons.movie_icon,
            "series": _icons.series_icon,
        }.get(channel.media_type or "", _icons.unknown_icon)
        self._media_type_lbl.setText(f"{media_icon} {(channel.media_type or 'unknown').title()}")
        self.runtime_label.hide()

        provider_id = getattr(channel, "provider_id", None)
        if provider_id is not None:
            provider_info = (provider_map or {}).get(provider_id)
            if provider_info:
                icon = provider_info.get("icon", "")
                name = provider_info.get("name", "")
                badge = f"{icon} {name}".strip() if icon else name
                label_text = f"Source: {badge}" if badge else f"Source: {provider_id}"
            else:
                label_text = f"Source: (source removed) [{provider_id}]"
            self.source_label.setText(label_text)
            # Store channel ID for click-to-copy and add tooltip
            self.source_label.channel_id = channel.id
            self.source_label.setToolTip(f"ID: {channel.id}\n(Click to copy)")
            self.source_label.show()

        if getattr(channel, "is_adult", False):
            self.adult_indicator.show()
        else:
            self.adult_indicator.hide()

        # Watch-completion status (VOD movies only — never shown for live/series).
        # Reads stored watch_completed / watch_progress fields; never recomputes.
        is_movie = getattr(channel, "media_type", None) == "movie"
        if is_movie:
            watch_completed = bool(getattr(channel, "watch_completed", False))
            watch_progress = int(getattr(channel, "watch_progress", 0) or 0)
            if watch_completed:
                self._watch_status_lbl.setText(f"{_icons.watched_icon} Watched")
                self._watch_status_lbl.setStyleSheet(_theme.WATCH_STATUS_DONE)
                self._watch_status_lbl.setToolTip("You have finished watching this title.")
                self._watch_status_lbl.show()
            elif watch_progress > 0:
                minutes, secs = divmod(watch_progress, 60)
                resume_str = f"{minutes}:{secs:02d}"
                self._watch_status_lbl.setText(f"{_icons.episode_icon} Resume at {resume_str}")
                self._watch_status_lbl.setStyleSheet(_theme.WATCH_STATUS_PROGRESS)
                self._watch_status_lbl.setToolTip(f"Playback paused at {resume_str}. Resume from here.")
                self._watch_status_lbl.show()
            else:
                self._watch_status_lbl.hide()
        else:
            self._watch_status_lbl.hide()

        # Show rating from raw_data immediately (don't wait for metadata).
        # rating_label lives on the media-type row so no separate row to show/hide.
        if channel.raw_data:
            raw_rating = channel.raw_data.get("rating")
            if raw_rating:
                try:
                    rating_val = float(raw_rating)
                    rating_val = max(0.0, min(10.0, rating_val))  # clamp to 0-10
                    stars = self.config.rating_star_icon * int(rating_val / 2)
                    self.rating_label.setText(f"{stars} {rating_val:.1f} of 10")
                    self.rating_label.show()
                except (ValueError, TypeError):
                    self.rating_label.hide()
            else:
                self.rating_label.hide()
        else:
            self.rating_label.hide()

        # Show loading indicator for categories (will be populated by load_metadata).
        # LIVE channels have no metadata genres — hide the area; the version chips
        # (set_versions) handle their category display instead.
        if getattr(channel, "media_type", None) == "live":
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
        else:
            self._genres_container.hide()
            self._genres_loading_lbl.setText(f"{_icons.loading_icon} Loading categories...")
            self._genres_loading_lbl.show()

    def load_metadata(self, metadata: MetadataResult) -> None:
        """Tier-2/3 display: enrich with metadata fields."""
        if metadata.title:
            parsed = parse_channel_name(metadata.title)
            clean = parsed.bare_name if parsed.bare_name else metadata.title
            self.title_label.setText(clean)
            if parsed.year and not self._name_year_lbl.isVisible():
                self._name_year_lbl.setText(parsed.year)
                self._name_year_lbl.show()

        if metadata.tagline:
            self._tagline_lbl.setText(metadata.tagline)
            self._tagline_lbl.show()

        if metadata.year:
            self._name_year_lbl.setText(str(metadata.year))
            self._name_year_lbl.show()

        if metadata.rating:
            count_str = (
                f" by {metadata.rating_count:,} votes" if metadata.rating_count else ""
            )
            stars = self.config.rating_star_icon * int(metadata.rating / 2)
            self.rating_label.setText(f"{stars} {metadata.rating:.1f} of 10{count_str}")
            self.rating_label.show()

        if metadata.content_rating:
            self._content_rating_lbl.setText(metadata.content_rating)
            self._content_rating_lbl.show()

        if metadata.runtime:
            h, m = divmod(metadata.runtime, 60)
            self.runtime_label.setText(f"{h}h {m}m" if h else f"{m}m")
            self.runtime_label.show()

        if metadata.imdb_id:
            self._imdb_lbl.setText(f"IMDb {metadata.imdb_id}")
            self._imdb_lbl.show()

        if metadata.tmdb_id:
            self._tmdb_lbl.setText(f"TMDb {metadata.tmdb_id}")
            self._tmdb_lbl.show()

        self._genres_loading_lbl.hide()
        if metadata.genres:
            genres: list[str] = []
            for g in metadata.genres:
                if isinstance(g, str) and re.search(r'\s*/\s*', g):
                    genres.extend(p.strip() for p in g.split('/') if p.strip())
                else:
                    genres.append(g)
            self._populate_genre_chips(genres)
        else:
            # No genres available — hide the container too
            self._genres_container.hide()

    def set_recommendation_reason(self, reason: str | None) -> None:
        if reason:
            self.rec_reason_label.setText(f"{self.config.preferences_icon} Recommended: {reason}")
            self.rec_reason_label.show()
        else:
            self.rec_reason_label.hide()

    def clear(self) -> None:
        self.title_label.clear()
        self._prefix_chip.hide()
        self._quality_chip.hide()
        self._name_year_lbl.hide()
        self._tagline_lbl.hide()
        self._media_type_lbl.clear()
        self.runtime_label.hide()
        self._imdb_lbl.hide()
        self._tmdb_lbl.hide()
        self.rating_label.clear()
        self.rating_label.hide()
        self._content_rating_lbl.hide()
        self._genres_loading_lbl.hide()
        self._clear_genre_chips()
        self._genres_container.hide()
        self.source_label.clear()
        self.source_label.hide()
        self.adult_indicator.hide()
        self._watch_status_lbl.hide()
        self.rec_reason_label.hide()

    # ------------------------------------------------------------------ #
    # Genre chips — private helpers                                        #
    # ------------------------------------------------------------------ #

    def _clear_genre_chips(self) -> None:
        """Remove all genre chip buttons from the flow layout."""
        while self._genres_layout.count():
            item = self._genres_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    def _populate_genre_chips(self, genres: list[str]) -> None:
        """Replace the flow layout contents with one chip button per genre."""
        self._clear_genre_chips()
        for g in genres:
            chip = QPushButton(g)
            chip.setFlat(True)
            chip.setStyleSheet(_theme.GENRE_CHIP)
            chip.setToolTip(f"Filter by genre: {g}")
            chip.clicked.connect(lambda _checked, _g=g: self.genre_clicked.emit(_g))
            self._genres_layout.addWidget(chip)
        self._genres_container.updateGeometry()
        self._genres_container.show()


# ---------------------------------------------------------------------------
# _PlotSection
# ---------------------------------------------------------------------------

class _PlotSection(QWidget):
    """Overview header + plot text + loading indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = QLabel("<b>Overview</b>")
        layout.addWidget(self._header)

        self.plot_label = QLabel()
        self.plot_label.setWordWrap(True)
        self.plot_label.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_label.setStyleSheet(_theme.DETAIL_TEXT)
        layout.addWidget(self.plot_label)

        self.plot_loading = QLabel("Loading description...")
        self.plot_loading.setStyleSheet(_theme.LOADING_TEXT)
        self.plot_loading.hide()
        layout.addWidget(self.plot_loading)

    def set_mode(self, is_live: bool) -> None:
        self.setVisible(not is_live)

    def load(self, plot: str | None, loading_icon: str = "") -> None:
        if plot:
            self.plot_label.setText(plot)
            self.plot_loading.hide()
        else:
            self.plot_label.clear()

    def show_loading(self, loading_icon: str = "") -> None:
        self.plot_loading.setText(f"{loading_icon} Loading metadata..." if loading_icon else "Loading metadata...")
        self.plot_loading.show()

    def clear(self) -> None:
        self.plot_label.clear()
        self.plot_loading.hide()


# ---------------------------------------------------------------------------
# _TechnicalSection
# ---------------------------------------------------------------------------

class _TechnicalSection(QWidget):
    """Collapsible Technical Details section."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)
        self._toggle_btn = QPushButton(self.config.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel("<b>Technical Details</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        # Content
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        self.tech_details_label = QLabel()
        self.tech_details_label.setWordWrap(True)
        self.tech_details_label.setTextFormat(Qt.TextFormat.RichText)
        self.tech_details_label.setStyleSheet(_theme.DETAIL_TEXT)
        content_layout.addWidget(self.tech_details_label)
        layout.addWidget(self._content)

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "technical" in collapsed_sections
        self._apply()

    def set_mode(self, is_live: bool) -> None:
        if is_live:
            self.hide()
        else:
            self._apply()

    def load(self, metadata: MetadataResult, weights=None) -> bool:
        """Populate section. Returns True if there is anything to display."""
        parts = []
        if metadata.release_date:
            parts.append(f"<b>Release Date:</b> {metadata.release_date}")
        self.tech_details_label.setText("<br>".join(parts))
        has_content = bool(parts)
        self.setVisible(has_content)
        return has_content

    def clear(self) -> None:
        self.tech_details_label.clear()
        self.hide()

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            self.config.expand_icon if self._collapsed else self.config.collapse_icon
        )

    def is_collapsed(self) -> bool:
        return self._collapsed

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("technical")
        else:
            sections.discard("technical")
        config.details_pane_collapsed_sections = list(sections)
        config.save()


# ---------------------------------------------------------------------------
# _CastSection
# ---------------------------------------------------------------------------

class _CastSection(QWidget):
    """Collapsible Cast & Crew section."""

    person_clicked = pyqtSignal(str)  # emits the person's name when clicked

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)
        self._toggle_btn = QPushButton(self.config.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel("<b>Cast & Crew</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        content_layout.setSpacing(4)

        self._director_lbl = QLabel()
        self._director_lbl.setWordWrap(True)
        self._director_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._director_lbl.setStyleSheet(_theme.DETAIL_TEXT)
        self._director_lbl.setOpenExternalLinks(False)
        self._director_lbl.linkActivated.connect(
            lambda url: self.person_clicked.emit(url)
        )
        self._director_lbl.hide()
        content_layout.addWidget(self._director_lbl)

        self.cast_label = QLabel()
        self.cast_label.setWordWrap(True)
        self.cast_label.setTextFormat(Qt.TextFormat.RichText)
        self.cast_label.setStyleSheet(_theme.DETAIL_TEXT)
        self.cast_label.setOpenExternalLinks(False)
        self.cast_label.linkActivated.connect(
            lambda url: self.person_clicked.emit(url)
        )
        content_layout.addWidget(self.cast_label)
        layout.addWidget(self._content)

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "cast" in collapsed_sections
        self._apply()

    def set_mode(self, is_live: bool) -> None:
        self._header_widget.setVisible(not is_live)
        if is_live:
            self._content.setVisible(False)
        else:
            self._apply()

    def load(self, cast: list, director: str | None = None, weights=None) -> None:
        link_col = _theme.COLOR_ACCENT_BLUE_2

        if director:
            from metatv.core.preference_engine import _split_directors
            names = _split_directors(director)
            dir_parts = []
            for d in names:
                sig = _pref_signal(d, weights, 'directors') if weights else ""
                href = html.escape(d, quote=True)
                link = (
                    f'{sig}<a href="{href}" style="color:{link_col};'
                    f' text-decoration:none;">{html.escape(d)}</a>'
                )
                dir_parts.append(link)
            self._director_lbl.setText(f"<b>Director:</b> {', '.join(dir_parts)}")
            self._director_lbl.show()
        else:
            self._director_lbl.hide()

        if not cast:
            self.cast_label.clear()
            return
        parts = []
        for actor in cast[:10]:
            name = actor.get("name", "Unknown") if isinstance(actor, dict) else str(actor)
            sig = _pref_signal(name, weights, "actors") if weights else ""
            href = html.escape(name, quote=True)
            parts.append(
                f'{sig}<a href="{href}" style="color:{link_col};'
                f' text-decoration:none;">{html.escape(name)}</a>'
            )
        self.cast_label.setText(", ".join(parts))

    def clear(self) -> None:
        self._director_lbl.hide()
        self.cast_label.clear()

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            self.config.expand_icon if self._collapsed else self.config.collapse_icon
        )

    def is_collapsed(self) -> bool:
        return self._collapsed

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("cast")
        else:
            sections.discard("cast")
        config.details_pane_collapsed_sections = list(sections)
        config.save()


# ---------------------------------------------------------------------------
# _TagsSection
# ---------------------------------------------------------------------------

# Canonical display order for facet groups in the Tags section.
# "category" sits immediately before "genre" — both are content descriptors;
# category is the live-channel variant (Sports/News/Kids…).
_FACET_DISPLAY_ORDER: list[str] = [
    "language", "subtitle", "dub", "format",
    "region", "category", "genre", "platform", "quality", "decade", "collection",
]

# Human-readable label for each facet type.
_FACET_LABELS: dict[str, str] = {
    "language":    "Language",
    "subtitle":    "Subtitle",
    "dub":         "Dub",
    "format":      "Audio Format",
    "region":      "Region",
    "category":    "Category",
    "genre":       "Genre",
    "platform":    "Platform",
    "quality":     "Quality",
    "decade":      "Decade",
    "collection":  "Collection",
    "content_type": "Content Type",
}

# Confidence threshold below which a chip is styled as low-confidence.
_LOW_CONF_THRESHOLD: float = 0.5


class _TagsSection(QWidget):
    """Collapsible 'Tags' section showing stored content_tags, grouped by facet.

    Each tag renders as a chip labeled with:
    - Provenance: solid border = source-given; dashed border = inferred.
    - Confidence: dimmed chip text for tags with confidence < 0.5.
    - Tooltip: feeder names + provenance label + confidence value.

    DR-0006: all tags are shown regardless of confidence — confidence is
    ranking + prune-priority only, never a suppression gate.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._setup()

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Collapsible header
        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)

        self._toggle_btn = QPushButton(_icons.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel(f"<b>{_icons.tag_section_icon} Tags</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        # Scrollable content area — chips can wrap into many rows
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 0, 0, 6)
        self._content_layout.setSpacing(6)
        layout.addWidget(self._content)

        # Initially hidden until tags are loaded
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load(self, tags: list) -> None:
        """Populate section from a list of ChannelTagDTO objects.

        Args:
            tags: List of ``ChannelTagDTO`` — must not be ORM objects.
                  Renders all tags grouped by facet in display order.
        """
        self._clear_content()

        if not tags:
            self.hide()
            return

        # Group by facet type, preserving DR-0006 "capture all" principle.
        grouped: dict[str, list] = {}
        for tag in tags:
            grouped.setdefault(tag.facet_type, []).append(tag)

        # Sort within each facet: source-given first, then by confidence desc, then value.
        for facet_tags in grouped.values():
            facet_tags.sort(key=lambda t: (not t.source_given, -t.confidence, t.value))

        # Render in canonical display order; any unknown facets appended at the end.
        ordered_facets: list[str] = [
            f for f in _FACET_DISPLAY_ORDER if f in grouped
        ]
        ordered_facets.extend(
            f for f in sorted(grouped) if f not in _FACET_DISPLAY_ORDER
        )

        for facet in ordered_facets:
            self._render_facet_group(facet, grouped[facet])

        self._apply()
        self.show()

    def clear(self) -> None:
        """Clear all chips and hide the section."""
        self._clear_content()
        self.hide()

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "tags" in collapsed_sections
        self._apply()

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("tags")
        else:
            sections.discard("tags")
        config.details_pane_collapsed_sections = list(sections)
        config.save()

    def is_collapsed(self) -> bool:
        return self._collapsed

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _clear_content(self) -> None:
        """Remove all child widgets from the content layout."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render_facet_group(self, facet: str, tags: list) -> None:
        """Render a labeled chip row for one facet group."""
        label_text = _FACET_LABELS.get(facet, facet.replace("_", " ").title())

        # Facet label (e.g. "LANGUAGE")
        lbl = QLabel(label_text.upper())
        lbl.setStyleSheet(_theme.TAG_FACET_LABEL)
        self._content_layout.addWidget(lbl)

        # Chip row — wrapped with QHBoxLayout + stretch to left-align
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        for tag in tags:
            chip = self._make_chip(tag)
            row_layout.addWidget(chip)

        row_layout.addStretch()
        self._content_layout.addWidget(row)

    def _make_chip(self, tag) -> QPushButton:
        """Build a single QPushButton chip for a ChannelTagDTO."""
        # Provenance prefix: ■ = source-given, □ = inferred
        prov_icon = (
            _icons.tag_source_given_icon if tag.source_given
            else _icons.tag_inferred_icon
        )
        label = f"{prov_icon} {tag.value}"

        chip = QPushButton(label)
        chip.setFlat(True)
        chip.setFixedHeight(22)

        # Provenance style: source-given = solid border; inferred = dashed border.
        # Low-confidence = extra dimming on top of provenance style.
        if tag.source_given:
            chip.setStyleSheet(_theme.TAG_CHIP_SOURCE)
        else:
            chip.setStyleSheet(_theme.TAG_CHIP_INFERRED)

        # Tooltip: feeder list + provenance label + confidence value
        prov_label = "Given by source" if tag.source_given else "Inferred by MetaTV"
        feeder_str = ", ".join(tag.feeders) if tag.feeders else "unknown"
        conf_pct = round(tag.confidence * 100)
        conf_note = "" if tag.confidence >= _LOW_CONF_THRESHOLD else " (low confidence)"
        chip.setToolTip(
            f"{tag.facet_type}: {tag.value}\n"
            f"Provenance: {prov_label}\n"
            f"Feeder(s): {feeder_str}\n"
            f"Confidence: {conf_pct}%{conf_note}"
        )

        return chip

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            _icons.expand_icon if self._collapsed else _icons.collapse_icon
        )
