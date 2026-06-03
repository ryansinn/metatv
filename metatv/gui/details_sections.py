"""Content section widgets for the details pane: poster, metadata, plot, technical, cast."""
import re

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.channel_name_utils import (
    normalize_region_code, REGION_FULL_NAMES, QUALITY_TOKENS, parse_channel_name,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_versions import _CHANNEL_PREFIX_RE, resolve_category_name
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


# ---------------------------------------------------------------------------
# _PosterSection
# ---------------------------------------------------------------------------

class _PosterSection(QWidget):
    """Poster image (VOD) and live-channel header (icon + country info)."""

    def __init__(self, config, image_cache, parent=None):
        super().__init__(parent)
        self.config = config
        self._image_cache = image_cache
        self._poster_url: str | None = None
        self._logo_url: str | None = None
        self._provider_urls: list = []
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Poster label (VOD)
        self._poster_frame = QWidget()
        pf_layout = QVBoxLayout(self._poster_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)

        self.poster_label = QLabel()
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setMinimumHeight(400)
        self.poster_label.setMaximumHeight(600)
        self.poster_label.setStyleSheet(
            f"QLabel {{ background-color: rgba(0,0,0,0.3); border-radius: 8px;"
            f" color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM}; }}"
        )
        self.poster_label.setScaledContents(False)
        self.poster_label.setText("No poster available")
        pf_layout.addWidget(self.poster_label)

        layout.addWidget(self._poster_frame)

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
        self._country_info_lbl.setStyleSheet("font-size: 11px; color: #777; font-style: italic;")
        self._country_info_lbl.setWordWrap(True)
        self._country_info_lbl.hide()
        live_layout.addWidget(self._country_info_lbl, 1)

        self._live_header.hide()
        layout.addWidget(self._live_header)

    def set_mode(self, is_live: bool) -> None:
        self._poster_frame.setVisible(not is_live)
        self._live_header.setVisible(is_live)

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
        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText("No poster available")
        self._country_info_lbl.hide()
        self._channel_icon_lbl.hide()

    def _display_poster(self, pixmap: QPixmap) -> None:
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.poster_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.poster_label.setPixmap(scaled)
        else:
            self.poster_label.setText("No poster available")


# ---------------------------------------------------------------------------
# _MetadataSection
# ---------------------------------------------------------------------------

class _MetadataSection(QWidget):
    """Title, year, rating, genres, source badge, adult indicator, rec reason."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Title bar: [prefix chip]  [clean title ···]  [year]
        title_bar = QWidget()
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)
        title_bar_layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(_theme.DETAIL_TITLE)
        title_bar_layout.addWidget(self.title_label, 1)

        self._prefix_chip = QPushButton()
        self._prefix_chip.setFlat(True)
        self._prefix_chip.setStyleSheet(_theme.CATEGORY_CHIP)
        self._prefix_chip.setFixedHeight(24)
        self._prefix_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._prefix_chip.hide()
        title_bar_layout.addWidget(self._prefix_chip)

        self._name_year_lbl = QLabel()
        self._name_year_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_MUTED}; font-weight: bold;"
        )
        self._name_year_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._name_year_lbl.hide()
        title_bar_layout.addWidget(self._name_year_lbl)

        layout.addWidget(title_bar)

        # Metadata row (year, rating, runtime)
        self._meta_row = QWidget()
        meta_row_layout = QHBoxLayout(self._meta_row)
        meta_row_layout.setContentsMargins(0, 0, 0, 0)
        self.year_label = QLabel()
        self.year_label.setStyleSheet(_theme.META_DIM)
        meta_row_layout.addWidget(self.year_label)
        self.rating_label = QLabel()
        self.rating_label.setStyleSheet("color: gold; font-weight: bold;")
        meta_row_layout.addWidget(self.rating_label)
        self.runtime_label = QLabel()
        self.runtime_label.setStyleSheet(_theme.META_DIM)
        meta_row_layout.addWidget(self.runtime_label)
        meta_row_layout.addStretch()
        layout.addWidget(self._meta_row)

        # Source badge + adult indicator row
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
        layout.addLayout(badge_row)

        # Genres
        self.genres_label = QLabel()
        self.genres_label.setWordWrap(True)
        self.genres_label.setStyleSheet("color: lightblue;")
        layout.addWidget(self.genres_label)

        # Recommendation reason
        self.rec_reason_label = QLabel()
        self.rec_reason_label.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic;")
        self.rec_reason_label.setWordWrap(True)
        self.rec_reason_label.hide()
        layout.addWidget(self.rec_reason_label)

    def set_mode(self, is_live: bool) -> None:
        self._meta_row.setVisible(not is_live)
        self.genres_label.setVisible(not is_live)
        if is_live:
            self.title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        else:
            self.title_label.setStyleSheet(_theme.DETAIL_TITLE)

    def load_basic(self, channel, provider_map: dict | None = None) -> None:
        """Tier-1 display: channel attributes only, no metadata."""
        parsed = parse_channel_name(channel.name)
        clean_title = parsed.bare_name if parsed.bare_name else channel.name
        self.title_label.setText(clean_title)

        # Prefix chip — shows detected category code (EN, NF, D+, etc.).
        # Quality tokens (4K, HD, etc.) are not region/platform chips; skip them.
        prefix = parsed.region or getattr(channel, "detected_prefix", None) or ""
        if prefix and prefix.upper() not in QUALITY_TOKENS:
            tip = resolve_category_name(prefix, self.config) or prefix
            self._prefix_chip.setText(prefix)
            self._prefix_chip.setToolTip(tip)
            self._prefix_chip.show()
        else:
            self._prefix_chip.hide()

        # Year from channel name — shown to the right of the title
        if parsed.year:
            self._name_year_lbl.setText(parsed.year)
            self._name_year_lbl.show()
        else:
            self._name_year_lbl.hide()

        media_icon = {
            "live":   _icons.live_icon,
            "movie":  _icons.movie_icon,
            "series": _icons.series_icon,
        }.get(channel.media_type or "", _icons.unknown_icon)
        self.year_label.setText(f"{media_icon} {(channel.media_type or 'unknown').title()}")

        if provider_map:
            provider_info = provider_map.get(getattr(channel, "provider_id", None))
            if provider_info:
                icon = provider_info.get("icon", "")
                name = provider_info.get("name", "")
                badge = f"{icon} {name}".strip() if icon else name
                if badge:
                    self.source_label.setText(f"Source: {badge}")
                    self.source_label.show()

        if getattr(channel, "is_adult", False):
            self.adult_indicator.show()
        else:
            self.adult_indicator.hide()

    def load_metadata(self, metadata: MetadataResult) -> None:
        """Tier-2/3 display: enrich with metadata fields."""
        if metadata.title:
            parsed = parse_channel_name(metadata.title)
            clean = parsed.bare_name if parsed.bare_name else metadata.title
            self.title_label.setText(clean)
            if parsed.year and not self._name_year_lbl.isVisible():
                self._name_year_lbl.setText(parsed.year)
                self._name_year_lbl.show()
        if metadata.year:
            self.year_label.setText(str(metadata.year))
            self._name_year_lbl.setText(str(metadata.year))
            self._name_year_lbl.show()
        if metadata.rating:
            stars = self.config.rating_star_icon * int(metadata.rating / 2)
            self.rating_label.setText(f"{stars} {metadata.rating:.1f}/10")
        if metadata.runtime:
            h, m = divmod(metadata.runtime, 60)
            self.runtime_label.setText(f"{h}h {m}m" if h else f"{m}m")
        if metadata.genres:
            genres: list[str] = []
            for g in metadata.genres:
                if isinstance(g, str) and re.search(r'\s*/\s*', g):
                    genres.extend(p.strip() for p in g.split('/') if p.strip())
                else:
                    genres.append(g)
            self.genres_label.setText(" • ".join(genres))

    def set_recommendation_reason(self, reason: str | None) -> None:
        if reason:
            self.rec_reason_label.setText(f"{self.config.preferences_icon} Recommended: {reason}")
            self.rec_reason_label.show()
        else:
            self.rec_reason_label.hide()

    def clear(self) -> None:
        self.title_label.clear()
        self._prefix_chip.hide()
        self._name_year_lbl.hide()
        self.year_label.clear()
        self.rating_label.clear()
        self.runtime_label.clear()
        self.genres_label.clear()
        self.source_label.clear()
        self.source_label.hide()
        self.adult_indicator.hide()
        self.rec_reason_label.hide()


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
        self._header_widget.setVisible(not is_live)
        if is_live:
            self._content.setVisible(False)
        else:
            self._apply()

    def load(self, metadata: MetadataResult, weights=None) -> None:
        parts = []
        if metadata.release_date:
            parts.append(f"<b>Release Date:</b> {metadata.release_date}")
        if metadata.content_rating and not metadata.rating:
            parts.append(f"<b>Content Rating:</b> {metadata.content_rating}")
        if metadata.director:
            if weights:
                from metatv.core.preference_engine import _split_directors
                dir_parts = [
                    f"{_pref_signal(d, weights, 'directors')}{d}"
                    for d in _split_directors(metadata.director)
                ]
                dir_str = ", ".join(dir_parts)
            else:
                dir_str = metadata.director
            parts.append(f"<b>Director:</b> {dir_str}")
        if metadata.tmdb_id:
            parts.append(f"<b>TMDb ID:</b> {metadata.tmdb_id}")
        self.tech_details_label.setText("<br>".join(parts))

    def clear(self) -> None:
        self.tech_details_label.clear()

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
        self._director_lbl.hide()
        content_layout.addWidget(self._director_lbl)

        self.cast_label = QLabel()
        self.cast_label.setWordWrap(True)
        self.cast_label.setTextFormat(Qt.TextFormat.RichText)
        self.cast_label.setStyleSheet(_theme.DETAIL_TEXT)
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
        if director:
            if weights:
                from metatv.core.preference_engine import _split_directors
                dir_parts = [
                    f"{_pref_signal(d, weights, 'directors')}{d}"
                    for d in _split_directors(director)
                ]
                dir_str = ", ".join(dir_parts)
            else:
                dir_str = director
            self._director_lbl.setText(f"<b>Director:</b> {dir_str}")
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
            parts.append(f"{sig}{name}")
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
