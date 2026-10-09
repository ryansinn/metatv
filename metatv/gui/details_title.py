"""Details pane — the title block (DETAILS-3b).

Title, byline (type · year · runtime · content rating, plus the Adult
indicator), the genre-chip row, the rating/TMDb/IMDb row, the tagline, and the
source + collection chip row that sits just above "Available in".

Moved out of ``details_sections.py`` (pinned at its code-health ceiling) into
its own cohesive module — the class name ``_MetadataSection`` is kept so the
pane's one caller (``details_pane.py``) has an unchanged API: ``load_basic``,
``load_metadata``, ``set_mode``, ``clear``, ``set_recommendation_reason``, the
``genre_clicked`` signal, plus the new ``set_collection``,
``source_filter_requested``, ``collection_clicked`` and ``status_message``
members this slice adds.

Quality/region badges and the plain "Source:" label are gone from this block
— quality now lives on the "Available in" copy chips (a parallel slice), and
provenance is a clickable chip rather than static text.  The rating star
glyph is gone too: the rating renders as a plain "8.0 / 10", gold on the
number only, via :func:`_rating_rich_text`.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.core.filter_utils import normalize_genre
from metatv.core.models import MediaType
from metatv.core.tag_provenance import guess_reason, strongest_kind
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.detail_chips import make_chip, make_flow
from metatv.gui.details_sections import _is_stale_polluted_title
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.qt_size_utils import no_width_force as _no_width_force
from metatv.gui.qt_text_utils import escape_mnemonic
from metatv.metadata_providers.base import MetadataResult


def _rating_rich_text(rating: float) -> str:
    """"<gold bold>8.0</gold> / 10" — never a star glyph.

    The number is ``COLOR_GOLD`` and bold; the "/ 10" is the plain
    ``COLOR_TEXT`` ramp.  Both are TOKEN references resolved at call time
    (same convention as ``_pref_signal`` in ``details_sections.py``), not a
    hardcoded hex literal — this is rich-text content, not a stylesheet, so
    it is rebuilt on every ``load_basic``/``load_metadata`` call rather than
    re-applied by ``theme.style_fn`` on a palette switch.
    """
    return (
        f"<span style='color:{_theme.COLOR_GOLD}; font-weight:bold;'>{rating:.1f}</span>"
        f"<span style='color:{_theme.COLOR_TEXT};'> / 10</span>"
    )


class _MetadataSection(QWidget):
    """Title, byline, genre chips, rating/id chips, tagline, source/collection chips."""

    genre_clicked = pyqtSignal(str)            # genre name — left-click a genre chip
    collection_clicked = pyqtSignal(str)        # collection value — left-click the collection chip
    source_filter_requested = pyqtSignal(str)   # provider_id — left-click the source chip
    status_message = pyqtSignal(str)            # one-line status text — id-chip copy feedback

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._byline_kind = ""
        self._byline_year = ""
        self._byline_runtime = ""
        self._byline_content_rating = ""
        self._is_live = False
        self._metadata_genres: list[str] = []
        self._tag_genre_items: list = []
        self._tmdb_id: str | None = None
        self._imdb_id: str | None = None
        self._media_type: str = ""
        self._source_provider_id: str | None = None
        self._source_channel_id: str | None = None
        self._source_text: str = ""
        self._source_name: str | None = None
        self._collection_value: str | None = None
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        # 8px bottom margin on the block: with the pane's own inter-section
        # spacing this opens a clear gap before "Available in" (point 5).
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        # Title bar — unchanged.  Nothing else shares the row, so a long
        # title gets (effectively) the whole width to wrap in.
        title_bar = QWidget()
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)
        title_bar_layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        _title_policy = QSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        _title_policy.setHeightForWidth(True)
        self.title_label.setSizePolicy(_title_policy)
        _theme.style(self.title_label, "DETAIL_TITLE")
        title_bar_layout.addWidget(self.title_label, 1)
        layout.addWidget(title_bar)

        # Byline — "Movie · 2024 · 2h 28m · PG-13" — plus the 🔞 Adult
        # indicator on the SAME row when the title is adult.
        byline_row = QWidget()
        byline_row_layout = QHBoxLayout(byline_row)
        byline_row_layout.setContentsMargins(0, 0, 0, 0)
        byline_row_layout.setSpacing(8)

        self._byline_lbl = QLabel()
        _theme.style(self._byline_lbl, "DETAIL_BYLINE")
        _no_width_force(self._byline_lbl)
        self._byline_lbl.hide()
        byline_row_layout.addWidget(self._byline_lbl, 1)

        self.adult_indicator = QLabel("🔞 Adult")
        _theme.style_fn(self.adult_indicator, lambda: f"color: {_theme.COLOR_ERR_2}; font-size: {_theme.FONT_MD}; font-weight: 600;"
            f" background: {_theme.OVERLAY_ERR2_15}; border-radius: 3px; padding: 1px 5px;")
        self.adult_indicator.hide()
        byline_row_layout.addWidget(self.adult_indicator)
        layout.addWidget(byline_row)

        # Genres — metadata genres first, then tag genres (facet "genre") not
        # already present; a guessed tag genre renders dashed.  A wrapping
        # flow row so it never forces the pane wider than its viewport.
        self._genres_loading_lbl = QLabel()
        _theme.style_fn(self._genres_loading_lbl, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
        self._genres_loading_lbl.hide()
        layout.addWidget(self._genres_loading_lbl)

        self._genres_container = QWidget()
        self._genres_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self._genres_layout = FlowLayout(self._genres_container, h_spacing=4, v_spacing=4)
        self._genres_container.hide()
        layout.addWidget(self._genres_container)

        # Rating row — "8.0 / 10" (no stars) + framed TMDb/IMDb chips, shown
        # only when the id exists.  Left-click a chip copies its id and
        # reports status; right-click offers Copy/Open on {TMDb,IMDb}.
        self.rating_label = QLabel()
        self.rating_label.setTextFormat(Qt.TextFormat.RichText)
        self.rating_label.setFixedHeight(make_chip("x").sizeHint().height())
        self.rating_label.hide()

        self._tmdb_chip = make_chip("TMDb")
        self._tmdb_chip.hide()
        # Bound slots + a property, never a lambda over ``self``: a closure that
        # captures the widget it is connected on is a reference cycle the
        # top-level-widget leak guard (tests/conftest.py) rightly reports.
        self._tmdb_chip.setProperty("id_kind", "tmdb")
        self._tmdb_chip.clicked.connect(self._on_id_chip_sender_clicked)
        self._tmdb_chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tmdb_chip.customContextMenuRequested.connect(self._on_id_chip_menu_requested)

        self._imdb_chip = make_chip("IMDb")
        self._imdb_chip.hide()
        # Bound slots + a property, never a lambda over ``self``: a closure that
        # captures the widget it is connected on is a reference cycle the
        # top-level-widget leak guard (tests/conftest.py) rightly reports.
        self._imdb_chip.setProperty("id_kind", "imdb")
        self._imdb_chip.clicked.connect(self._on_id_chip_sender_clicked)
        self._imdb_chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._imdb_chip.customContextMenuRequested.connect(self._on_id_chip_menu_requested)

        self._rating_row_w = make_flow([self.rating_label, self._tmdb_chip, self._imdb_chip])
        self._rating_row_w.hide()
        layout.addWidget(self._rating_row_w)

        # Tagline — italic subtitle line, shown when metadata provides it.
        self._tagline_lbl = QLabel()
        self._tagline_lbl.setWordWrap(True)
        _theme.style_fn(self._tagline_lbl, lambda: f"color: {_theme.COLOR_TEXT}; font-style: italic; font-size: {_theme.FONT_MD};")
        _no_width_force(self._tagline_lbl)
        self._tagline_lbl.hide()
        layout.addWidget(self._tagline_lbl)

        # Source row — NO label: the source chip (provider icon+name, or
        # "(source removed)") plus this copy's collection chip when one is
        # known.  Left-click the source chip filters the list to that
        # source; left-click the collection chip filters to that collection;
        # right-click the source chip offers "Copy channel id".
        self._source_chip = make_chip("")
        self._source_chip.clicked.connect(self._on_source_chip_clicked)
        self._source_chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._source_chip.customContextMenuRequested.connect(self._show_source_chip_menu)

        self._collection_chip = make_chip("", "COLOR_FACET_COLLECTION")
        self._collection_chip.clicked.connect(self._on_collection_chip_clicked)
        self._collection_chip.hide()

        self._source_row_w = make_flow([self._source_chip, self._collection_chip])
        self._source_row_w.hide()
        layout.addWidget(self._source_row_w)

        # Recommendation reason
        self.rec_reason_label = QLabel()
        _theme.style_fn(self.rec_reason_label, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; font-style: italic;")
        self.rec_reason_label.setWordWrap(True)
        _no_width_force(self.rec_reason_label)
        self.rec_reason_label.hide()
        layout.addWidget(self.rec_reason_label)

    def set_mode(self, is_live: bool) -> None:
        self._is_live = is_live
        self._refresh_rating_row_visibility()
        if is_live:
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
            _theme.style_fn(self.title_label, lambda: f"font-size: {_theme.FONT_4XL}; font-weight: bold;")
            self._tagline_lbl.hide()
        else:
            _theme.style(self.title_label, "DETAIL_TITLE")

    def _refresh_byline(self) -> None:
        """Rebuild "Movie · 2024 · 2h 28m · PG-13" from whichever parts are known.

        Called from both the tier-1 load and the metadata pass, because the
        year can arrive in either and runtime/content rating only ever
        arrive with metadata; rebuilding from the stored parts means a later
        caller never has to know what an earlier one already wrote.
        """
        parts = [p for p in (
            self._byline_kind, self._byline_year,
            self._byline_runtime, self._byline_content_rating,
        ) if p]
        self._byline_lbl.setText(" · ".join(parts))
        self._byline_lbl.setVisible(bool(parts))

    def _refresh_rating_row_visibility(self) -> None:
        """Hide the rating row when it has nothing to show, or in live mode."""
        has_content = (
            not self.rating_label.isHidden()
            or not self._tmdb_chip.isHidden()
            or not self._imdb_chip.isHidden()
        )
        self._rating_row_w.setVisible(has_content and not self._is_live)

    def load_basic(self, channel, provider_map: dict | None = None) -> None:
        """Tier-1 display: channel attributes only, no metadata.

        Reads stored detected_* fields written at ingestion time — never calls
        parse_channel_name() here (ingestion-only rule, CLAUDE.md).
        """
        clean_title = getattr(channel, "detected_title", None) or channel.name
        self._clean_display_title = clean_title  # fallback if metadata.title is a stale polluted copy
        self.title_label.setText(clean_title)
        self.title_label.setToolTip(channel.name)

        # Byline — kind and year, in that order, on the line under the title.
        self._byline_year = getattr(channel, "detected_year", None) or ""
        self._byline_kind = (channel.media_type or "unknown").title()
        self._media_type = channel.media_type or ""
        self._refresh_byline()

        # Source row — provider icon+name (or "(source removed)" for an
        # orphaned provider_id); hidden entirely when the channel has none.
        provider_id = getattr(channel, "provider_id", None)
        self._source_provider_id = provider_id
        self._source_channel_id = getattr(channel, "id", None)
        if provider_id is not None:
            provider_info = (provider_map or {}).get(provider_id)
            if provider_info:
                icon = provider_info.get("icon", "")
                name = provider_info.get("name", "")
                self._source_text = f"{icon} {name}".strip() if icon else name
                self._source_name = name
            else:
                self._source_text = f"(source removed) [{provider_id}]"
                self._source_name = None
        else:
            self._source_text = ""
            self._source_name = None
        self._rebuild_source_row()

        if getattr(channel, "is_adult", False):
            self.adult_indicator.show()
        else:
            self.adult_indicator.hide()

        # Show rating from raw_data immediately (don't wait for metadata).
        # A rating of 0 / "0" / "0.0" means "unrated" — hide it (don't show
        # "0.0 / 10").
        raw_rating = channel.raw_data.get("rating") if channel.raw_data else None
        try:
            rating_val = float(raw_rating) if raw_rating not in (None, "") else 0.0
        except (ValueError, TypeError):
            rating_val = 0.0
        if rating_val > 0:
            rating_val = min(10.0, rating_val)  # clamp upper bound
            self.rating_label.setText(_rating_rich_text(rating_val))
            self.rating_label.setToolTip("")
            self.rating_label.show()
        else:
            self.rating_label.hide()
        self._refresh_rating_row_visibility()

        # Show loading indicator for categories (will be populated by load_metadata
        # and/or set_genre_tags).  LIVE channels have no metadata genres — hide the
        # area; the version chips (set_versions) handle their category display.
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
            # Display the metadata title verbatim — never re-parse it at render
            # (ingestion-only rule, CLAUDE.md; see load_basic), except the one
            # stale-polluted-title case _is_stale_polluted_title selects around.
            _clean = getattr(self, "_clean_display_title", "")
            if not _is_stale_polluted_title(_clean, metadata.title):
                self.title_label.setText(metadata.title)

        if metadata.tagline:
            self._tagline_lbl.setText(metadata.tagline)
            self._tagline_lbl.show()

        if metadata.year:
            # Metadata year wins over the one parsed out of the channel name:
            # it comes from release_date, resolved at ingestion.
            self._byline_year = str(metadata.year)
            self._refresh_byline()

        if metadata.runtime:
            h, m = divmod(metadata.runtime, 60)
            self._byline_runtime = f"{h}h {m}m" if h else f"{m}m"
            self._refresh_byline()

        if metadata.content_rating:
            self._byline_content_rating = metadata.content_rating
            self._refresh_byline()

        if metadata.rating:
            self.rating_label.setText(_rating_rich_text(metadata.rating))
            if metadata.rating_count:
                self.rating_label.setToolTip(f"{metadata.rating_count:,} votes")
            self.rating_label.show()

        if metadata.imdb_id:
            self._imdb_id = metadata.imdb_id
            self._imdb_chip.setToolTip(
                f"IMDb {metadata.imdb_id} — click to copy the id, right-click to open on IMDb"
            )
            self._imdb_chip.show()

        if metadata.tmdb_id:
            self._tmdb_id = metadata.tmdb_id
            self._tmdb_chip.setToolTip(
                f"TMDb {metadata.tmdb_id} — click to copy the id, right-click to open on TMDb"
            )
            self._tmdb_chip.show()

        self._refresh_rating_row_visibility()

        if metadata.genres:
            # Providers deliver genres as a list, a slash-joined or a
            # comma-joined string; split on ',' and '/' (never '&' — "Sci-Fi &
            # Fantasy" is one TMDB genre), de-dupe case-insensitively, and fold
            # each leaf to its canonical key via normalize_genre — the same
            # table ingestion and stats use, so this pane agrees with the
            # row's detected_genre instead of showing the provider's raw
            # wording.
            genres: list[str] = []
            seen: set[str] = set()
            for g in metadata.genres:
                parts = re.split(r"\s*[/,]\s*", g) if isinstance(g, str) else [g]
                for p in parts:
                    name = p.strip() if isinstance(p, str) else p
                    if not name:
                        continue
                    if isinstance(name, str):
                        name = normalize_genre(name)
                    key = name.casefold() if isinstance(name, str) else name
                    if key in seen:
                        continue
                    seen.add(key)
                    genres.append(name)
            self._metadata_genres = genres
        else:
            self._metadata_genres = []
        self._rebuild_genre_row()

    def set_genre_tags(self, tags) -> None:
        """Merge tag-provenance genre facets into the genre row.

        Called from ``DetailsPaneWidget.apply_channel_tags`` with the
        facet_type == "genre" subset of the channel's tags (``ChannelTagDTO``).
        A tag not already present among the metadata genres renders as its
        own chip; one whose strongest feeder kind is "inference"
        (``tag_provenance.strongest_kind``) renders dashed, with a "Guessed
        ..." tooltip from ``tag_provenance.guess_reason``.
        """
        self._tag_genre_items = list(tags)
        self._rebuild_genre_row()

    def set_collection(self, value: str | None) -> None:
        """Set this copy's collection-facet tag value (or None).

        Called from ``DetailsPaneWidget.apply_channel_tags`` — the collection
        value arrives with the channel's tags, async, after ``load_basic``
        has already built the source row.
        """
        self._collection_value = value
        self._rebuild_source_row()

    def set_recommendation_reason(self, reason: str | None) -> None:
        if reason:
            self.rec_reason_label.setText(f"{self.config.preferences_icon} Recommended: {reason}")
            self.rec_reason_label.show()
        else:
            self.rec_reason_label.hide()

    def clear(self) -> None:
        self.title_label.clear()
        self._byline_kind = ""
        self._byline_year = ""
        self._byline_runtime = ""
        self._byline_content_rating = ""
        self._byline_lbl.hide()
        self._tagline_lbl.hide()
        self.rating_label.clear()
        self.rating_label.hide()
        self._tmdb_id = None
        self._imdb_id = None
        self._media_type = ""
        self._tmdb_chip.hide()
        self._imdb_chip.hide()
        self._refresh_rating_row_visibility()
        self._genres_loading_lbl.hide()
        self._metadata_genres = []
        self._tag_genre_items = []
        self._clear_genre_chips()
        self._genres_container.hide()
        self._source_provider_id = None
        self._source_channel_id = None
        self._source_text = ""
        self._source_name = None
        self._collection_value = None
        self._source_row_w.hide()
        self.adult_indicator.hide()
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
            chip = make_chip(g, "COLOR_FACET_GENRE")
            chip.setToolTip(f"Filter by genre: {g}")
            chip.setProperty("genre", g)
            chip.clicked.connect(self._on_genre_chip_clicked)
            self._genres_layout.addWidget(chip)
        self._genres_container.updateGeometry()
        self._genres_container.show()

    def _rebuild_genre_row(self) -> None:
        """Rebuild the genre row from the metadata genres plus any tag genres.

        Metadata genres render first (via ``_populate_genre_chips``, unchanged
        logic); tag genres not already present are appended, dashed when
        their strongest feeder kind is "inference".
        """
        if self._is_live:
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
            return
        self._populate_genre_chips(self._metadata_genres)
        seen = {g.casefold() for g in self._metadata_genres}
        for tag in self._tag_genre_items:
            if tag.value.casefold() in seen:
                continue
            seen.add(tag.value.casefold())
            guessed = strongest_kind(tag.feeders) == "inference"
            chip = make_chip(tag.value, "COLOR_FACET_GENRE", dashed=guessed)
            tip = f"Filter by genre: {tag.value}"
            if guessed:
                tip = f"Guessed {guess_reason(tag.feeders, [])} — {tip}"
            chip.setToolTip(tip)
            chip.setProperty("genre", tag.value)
            chip.clicked.connect(self._on_genre_chip_clicked)
            self._genres_layout.addWidget(chip)
        self._genres_loading_lbl.hide()
        self._genres_container.setVisible(self._genres_layout.count() > 0)

    # ------------------------------------------------------------------ #
    # Source / collection row — private helpers                            #
    # ------------------------------------------------------------------ #

    def _rebuild_source_row(self) -> None:
        if self._source_provider_id is None:
            self._source_row_w.hide()
            return
        self._source_chip.setText(escape_mnemonic(self._source_text))
        self._source_chip.setToolTip("Show everything from this source")
        if self._collection_value:
            self._collection_chip.setText(escape_mnemonic(self._collection_value))
            self._collection_chip.setToolTip(
                f"{self._source_name or 'This source'} files this copy under "
                f"{self._collection_value} — click to show the collection"
            )
            self._collection_chip.show()
        else:
            self._collection_chip.hide()
        self._source_row_w.show()

    def _on_source_chip_clicked(self) -> None:
        if self._source_provider_id:
            self.source_filter_requested.emit(self._source_provider_id)

    def _show_source_chip_menu(self, pos) -> None:
        if not self._source_channel_id:
            return
        menu = QMenu(self._source_chip)
        menu.addAction("Copy channel id").triggered.connect(self._copy_source_channel_id)
        menu.exec(self._source_chip.mapToGlobal(pos))
        menu.deleteLater()

    def _copy_source_channel_id(self) -> None:
        if self._source_channel_id:
            QApplication.clipboard().setText(self._source_channel_id)

    def _on_collection_chip_clicked(self) -> None:
        if self._collection_value:
            self.collection_clicked.emit(self._collection_value)

    # ------------------------------------------------------------------ #
    # Rating / TMDb / IMDb chips — private helpers                         #
    # ------------------------------------------------------------------ #

    def _on_genre_chip_clicked(self) -> None:
        """One slot for every genre chip; the chip carries its genre as a property."""
        genre = self.sender().property("genre") if self.sender() else None
        if genre:
            self.genre_clicked.emit(str(genre))

    def _on_id_chip_sender_clicked(self) -> None:
        kind = self.sender().property("id_kind") if self.sender() else None
        if kind:
            self._on_id_chip_clicked(str(kind))

    def _on_id_chip_menu_requested(self, pos) -> None:
        kind = self.sender().property("id_kind") if self.sender() else None
        if kind:
            self._show_id_chip_menu(str(kind), pos)

    def _on_id_chip_clicked(self, kind: str) -> None:
        ident = self._tmdb_id if kind == "tmdb" else self._imdb_id
        if not ident:
            return
        QApplication.clipboard().setText(ident)
        label = "TMDb" if kind == "tmdb" else "IMDb"
        self.status_message.emit(f"Copied {label} id {ident} to clipboard")

    def _show_id_chip_menu(self, kind: str, pos) -> None:
        ident = self._tmdb_id if kind == "tmdb" else self._imdb_id
        if not ident:
            return
        chip = self._tmdb_chip if kind == "tmdb" else self._imdb_chip
        label = "TMDb" if kind == "tmdb" else "IMDb"
        menu = QMenu(chip)
        menu.addAction(f"Copy {label} id").triggered.connect(
            lambda: self._on_id_chip_clicked(kind)
        )
        menu.addAction(f"Open on {label}").triggered.connect(
            lambda: self._open_id_on_web(kind)
        )
        menu.exec(chip.mapToGlobal(pos))
        menu.deleteLater()      # its action lambdas die with it — no lingering cycle

    def _open_id_on_web(self, kind: str) -> None:
        if kind == "tmdb" and self._tmdb_id:
            is_series = self._media_type == MediaType.SERIES
            url = f"https://www.themoviedb.org/{'tv' if is_series else 'movie'}/{self._tmdb_id}"
        elif kind == "imdb" and self._imdb_id:
            url = f"https://www.imdb.com/title/{self._imdb_id}"
        else:
            return
        QDesktopServices.openUrl(QUrl(url))
