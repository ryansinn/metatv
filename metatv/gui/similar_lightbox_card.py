"""The poster-hero content card for the Similar-Titles lightbox.

Split out of ``similar_lightbox.py`` so responsibilities read off the file
structure (self-documenting modularity, and both files stay well under the
1000-line limit):

- ``SimilarTitleLightbox`` (the overlay) owns the backdrop, prev/next chevrons,
  navigation state, the background DB read (``_bg_load``) and the ImageCache.
- ``_LightboxCard`` (here) owns the card's widget tree — header, poster hero,
  metadata, rating cluster, actions, Overview, Cast, **Other Versions**, the
  **Similar Titles** strip and the keyboard-hint footer — plus the populate
  logic.  It is a *dumb view*: it emits user intents as signals (the overlay
  attaches the current channel id and relays them) and exposes a single
  ``set_poster_pixmap`` seam so the overlay — which owns the ImageCache — can
  drive async image loading on the main thread (QPixmap is main-thread only).

The poster slot is deliberately built as a self-contained ``_HoverPosterSlot``
so a future embedded player can drop into the same footprint; hovering it reveals
a play affordance that fires the existing external ``play_requested`` path.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable
from metatv.gui.flow_layout import FlowLayout

# Poster / strip-card dimensions (structural spacing — px is fine inline).
_POSTER_W, _POSTER_H = 190, 285
_SIM_W, _SIM_H = 116, 174


def _fmt_runtime(minutes: int | None) -> str:
    """Return a human runtime like ``2h 9m`` / ``48m`` from whole minutes."""
    if not minutes or minutes <= 0:
        return ""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


_MEDIA_TYPE_ICON = {
    "movie": _icons.movie_icon,
    "series": _icons.series_icon,
    "live": _icons.live_icon,
}


class _ClickableFrame(QFrame):
    """A QFrame that emits :attr:`clicked` on a mouse press.

    Used for the similar-strip poster (the whole card is a dive-in target).  An
    instance-level ``mousePressEvent`` assignment does NOT override Qt's virtual
    dispatch, so this must be a real subclass.
    """

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


class _HoverPosterSlot(QFrame):
    """Static poster surface sized as the eventual embedded-player viewport.

    Hovering reveals a play orb; clicking the poster (or the orb) emits
    :attr:`clicked`, which the card relays to the overlay's external play path.
    A real player can later replace :attr:`_img` without moving anything else.
    """

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lightbox_poster")
        self.setFixedSize(_POSTER_W, _POSTER_H)
        self.setStyleSheet(_theme.LIGHTBOX_POSTER_SLOT)
        set_clickable(self)
        self.setToolTip("Play this title")

        self._img = QLabel(self)
        self._img.setGeometry(0, 0, _POSTER_W, _POSTER_H)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setWordWrap(True)
        self._img.setStyleSheet(_theme.LIGHTBOX_POSTER_PLACEHOLDER)
        # Let presses on the image fall through to the slot (play affordance).
        self._img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Play orb — hidden until hover.
        self._orb = QPushButton(_icons.play_icon, self)
        self._orb.setFixedSize(52, 52)
        self._orb.setStyleSheet(_theme.LIGHTBOX_PLAY_ORB)
        self._orb.setToolTip("Play this title")
        self._orb.move((_POSTER_W - 52) // 2, (_POSTER_H - 52) // 2)
        self._orb.clicked.connect(self.clicked)  # QPushButton auto-qualifies for the hand cursor
        self._orb.hide()

    # -- population ------------------------------------------------------- #
    def set_pixmap(self, pix: QPixmap) -> None:
        scaled = pix.scaled(
            QSize(_POSTER_W, _POSTER_H),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img.setPixmap(scaled)
        self._img.setText("")

    def set_placeholder(self, text: str) -> None:
        self._img.setPixmap(QPixmap())
        self._img.setText(text)

    # -- hover reveal ----------------------------------------------------- #
    def enterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._orb.setVisible(bool(self.isEnabled()))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._orb.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


class _LightboxCard(QFrame):
    """The lightbox content card (header + hero + sections + footer)."""

    # User intents relayed up to the overlay (which attaches the current id).
    back_clicked        = pyqtSignal()
    close_clicked       = pyqtSignal()
    play_clicked        = pyqtSignal()
    queue_clicked       = pyqtSignal()
    favorite_clicked    = pyqtSignal()
    hide_clicked        = pyqtSignal()
    rating_clicked      = pyqtSignal(int)   # +1 like / -1 dislike
    suppression_toggled = pyqtSignal(bool)  # Not-Interested on/off
    dive_requested      = pyqtSignal(str)   # channel_id (Other Version OR similar card)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lightbox_card")
        self.setStyleSheet(_theme.LIGHTBOX_CARD)
        self.setFixedWidth(820)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)

        # url → poster labels awaiting an async image (main poster + strip cards).
        self._poster_targets: dict[str, list[QLabel]] = {}
        self.main_poster_url: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._build_header(outer)
        self._build_body(outer)
        self._build_footer(outer)

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    def _build_header(self, outer: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(_theme.LIGHTBOX_HEADER_BAR)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(10)

        self._back_btn = QPushButton(f"{_icons.nav_prev_icon} Back")
        self._back_btn.setFlat(True)
        self._back_btn.setStyleSheet(_theme.LIGHTBOX_BACK_BTN)
        self._back_btn.setToolTip("Back to the previous title (Backspace)")
        self._back_btn.clicked.connect(self.back_clicked)
        self._back_btn.hide()
        row.addWidget(self._back_btn)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(_theme.LIGHTBOX_TITLE)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self._title_lbl, 1)

        self._counter_lbl = QLabel()
        self._counter_lbl.setStyleSheet(_theme.LIGHTBOX_COUNTER)
        row.addWidget(self._counter_lbl)

        close_btn = QPushButton(_icons.close_icon)
        close_btn.setFlat(True)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(_theme.LIGHTBOX_CLOSE_BTN)
        close_btn.setToolTip("Close preview (Esc)")
        close_btn.clicked.connect(self.close_clicked)
        row.addWidget(close_btn)

        outer.addWidget(bar)

    def _build_body(self, outer: QVBoxLayout) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(_theme.BG_TRANSPARENT)

        content = QWidget()
        content.setStyleSheet(_theme.BG_TRANSPARENT)
        body = QVBoxLayout(content)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(6)

        self._build_hero(body)
        self._build_overview(body)
        self._build_cast(body)
        self._build_other_versions(body)
        self._build_similar_strip(body)
        body.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _build_hero(self, body: QVBoxLayout) -> None:
        hero = QHBoxLayout()
        hero.setSpacing(20)
        hero.setContentsMargins(0, 0, 0, 0)

        # -- left: poster + primary Play + player-trajectory tag --
        left = QVBoxLayout()
        left.setSpacing(10)
        self._poster = _HoverPosterSlot()
        self._poster.clicked.connect(self.play_clicked)
        left.addWidget(self._poster, 0, Qt.AlignmentFlag.AlignHCenter)

        self._play_btn = QPushButton(f"{_icons.play_icon} Play")
        self._play_btn.setStyleSheet(_theme.LIGHTBOX_PLAY_PRIMARY)
        self._play_btn.setToolTip("Play this title")
        self._play_btn.clicked.connect(self.play_clicked)
        left.addWidget(self._play_btn)

        tag = QLabel("Preview — the player lands here later")
        tag.setStyleSheet(_theme.LIGHTBOX_PLAYER_TAG)
        tag.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tag.setWordWrap(True)
        left.addWidget(tag)
        left.addStretch()

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(_POSTER_W)
        hero.addWidget(left_w, 0)

        # -- right column --
        right = QVBoxLayout()
        right.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.setContentsMargins(0, 0, 0, 0)
        self._heading_lbl = QLabel()
        self._heading_lbl.setStyleSheet(_theme.LIGHTBOX_HEADING)
        self._heading_lbl.setWordWrap(True)
        title_row.addWidget(self._heading_lbl, 0)
        self._year_lbl = QLabel()
        self._year_lbl.setStyleSheet(_theme.LIGHTBOX_META)
        title_row.addWidget(self._year_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addStretch()
        right.addLayout(title_row)

        # Meta line — rebuilt per populate (rating · runtime · type · ×N versions).
        self._meta_row_w = QWidget()
        self._meta_row = QHBoxLayout(self._meta_row_w)
        self._meta_row.setContentsMargins(0, 4, 0, 0)
        self._meta_row.setSpacing(8)
        right.addWidget(self._meta_row_w)

        # Source attribution + active/live dot.
        src_row = QHBoxLayout()
        src_row.setContentsMargins(0, 6, 0, 0)
        src_row.setSpacing(6)
        self._source_dot = QLabel(_icons.status_dot_icon)
        src_row.addWidget(self._source_dot)
        self._source_lbl = QLabel()
        self._source_lbl.setStyleSheet(_theme.LIGHTBOX_SOURCE)
        src_row.addWidget(self._source_lbl)
        src_row.addStretch()
        self._source_row_w = QWidget()
        self._source_row_w.setLayout(src_row)
        right.addWidget(self._source_row_w)

        # Genre chips — DISPLAY ONLY (not clickable-to-Recipe yet).
        self._genres_w = QWidget()
        self._genres_flow = FlowLayout(self._genres_w, spacing=6)
        right.addWidget(self._genres_w)

        # Rating cluster (Like / Not-Interested / Dislike) — checkable, colourblind
        # safe: the distinct glyph carries state, the checked fill is reinforcement.
        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 10, 0, 0)
        rate_row.setSpacing(6)
        self._like_btn = self._make_rating_btn(_icons.like_icon, "Like")
        self._like_btn.clicked.connect(lambda: self.rating_clicked.emit(1))
        rate_row.addWidget(self._like_btn)
        self._not_interested_btn = self._make_rating_btn(
            _icons.not_interested_icon, "Not Interested (suppress from recommendations)"
        )
        self._not_interested_btn.clicked.connect(
            lambda checked: self.suppression_toggled.emit(checked)
        )
        rate_row.addWidget(self._not_interested_btn)
        self._dislike_btn = self._make_rating_btn(_icons.dislike_icon, "Dislike")
        self._dislike_btn.clicked.connect(lambda: self.rating_clicked.emit(-1))
        rate_row.addWidget(self._dislike_btn)
        rate_row.addStretch()
        right.addLayout(rate_row)

        # Library actions.
        act_row = QHBoxLayout()
        act_row.setContentsMargins(0, 10, 0, 0)
        act_row.setSpacing(7)
        self._queue_btn = QPushButton()
        self._queue_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._queue_btn.setToolTip("Add to / remove from Watch Queue")
        self._queue_btn.clicked.connect(self.queue_clicked)
        act_row.addWidget(self._queue_btn)
        self._fav_btn = QPushButton()
        self._fav_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._fav_btn.setToolTip("Add to / remove from Favorites")
        self._fav_btn.clicked.connect(self.favorite_clicked)
        act_row.addWidget(self._fav_btn)
        self._hide_btn = QPushButton(f"{_icons.hide_icon} Hide")
        self._hide_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._hide_btn.setToolTip("Hide this channel from all views")
        self._hide_btn.clicked.connect(self.hide_clicked)
        act_row.addWidget(self._hide_btn)
        act_row.addStretch()
        right.addLayout(act_row)
        right.addStretch()

        right_w = QWidget()
        right_w.setLayout(right)
        hero.addWidget(right_w, 1)
        body.addLayout(hero)

    def _make_rating_btn(self, glyph: str, tip: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setCheckable(True)
        btn.setFixedSize(38, 32)
        btn.setFlat(True)
        btn.setToolTip(tip)
        btn.setStyleSheet(_theme.RATING_BTN)
        return btn

    def _build_overview(self, body: QVBoxLayout) -> None:
        self._overview_hdr = self._section_header("OVERVIEW")
        body.addWidget(self._overview_hdr)
        self._plot_lbl = QLabel()
        self._plot_lbl.setWordWrap(True)
        self._plot_lbl.setStyleSheet(_theme.LIGHTBOX_PLOT)
        body.addWidget(self._plot_lbl)

    def _build_cast(self, body: QVBoxLayout) -> None:
        self._cast_hdr = self._section_header("CAST & CREW")
        body.addWidget(self._cast_hdr)
        self._cast_lbl = QLabel()
        self._cast_lbl.setWordWrap(True)
        self._cast_lbl.setStyleSheet(_theme.LIGHTBOX_CAST)
        body.addWidget(self._cast_lbl)

    def _build_other_versions(self, body: QVBoxLayout) -> None:
        self._versions_hdr = self._section_header("OTHER VERSIONS")
        body.addWidget(self._versions_hdr)
        self._versions_w = QWidget()
        self._versions_flow = FlowLayout(self._versions_w, spacing=8)
        body.addWidget(self._versions_w)

    def _build_similar_strip(self, body: QVBoxLayout) -> None:
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 8, 0, 0)
        hdr_row.setSpacing(10)
        self._similar_hdr = self._section_header("SIMILAR TITLES")
        hdr_row.addWidget(self._similar_hdr)
        hdr_row.addStretch()
        # Colourblind-safe: the ✓ glyph pairs with the green (colour is reinforcement).
        self._scoped_note = QLabel(
            f"{_icons.watched_icon} disabled & expired sources excluded"
        )
        self._scoped_note.setStyleSheet(_theme.LIGHTBOX_SCOPED_NOTE)
        hdr_row.addWidget(self._scoped_note)
        self._similar_hdr_row_w = QWidget()
        self._similar_hdr_row_w.setLayout(hdr_row)
        body.addWidget(self._similar_hdr_row_w)

        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setStyleSheet(_theme.BG_TRANSPARENT)
        self._strip_scroll.setFixedHeight(_SIM_H + 56)
        self._strip_w = QWidget()
        self._strip_w.setStyleSheet(_theme.BG_TRANSPARENT)
        self._strip_layout = QHBoxLayout(self._strip_w)
        self._strip_layout.setContentsMargins(0, 6, 0, 6)
        self._strip_layout.setSpacing(12)
        self._strip_layout.addStretch()
        self._strip_scroll.setWidget(self._strip_w)
        body.addWidget(self._strip_scroll)

    def _build_footer(self, outer: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(_theme.LIGHTBOX_FOOTER_BAR)
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(18)
        hints = [
            (f"{_icons.nav_prev_icon} {_icons.nav_next_icon}", "browse similar"),
            (_icons.lightbox_icon, "dive in"),
            ("Backspace", "back"),
            ("Esc", "close"),
        ]
        for key, text in hints:
            kbd = QLabel(key)
            kbd.setStyleSheet(_theme.LIGHTBOX_KBD)
            row.addWidget(kbd)
            lbl = QLabel(text)
            lbl.setStyleSheet(_theme.LIGHTBOX_FOOTER_HINT)
            row.addWidget(lbl)
        row.addStretch()
        outer.addWidget(bar)

    def _section_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_theme.LIGHTBOX_SECTION_HDR)
        lbl.setContentsMargins(0, 8, 0, 2)
        return lbl

    # ------------------------------------------------------------------ #
    # Header / navigation state (driven by the overlay)                    #
    # ------------------------------------------------------------------ #

    def set_header(self, origin_title: str) -> None:
        self._title_lbl.setText(f"Similar to:  {origin_title}")

    def set_counter(self, text: str) -> None:
        self._counter_lbl.setText(text)

    def set_back_visible(self, visible: bool) -> None:
        self._back_btn.setVisible(visible)

    # ------------------------------------------------------------------ #
    # Populate                                                             #
    # ------------------------------------------------------------------ #

    def reset_loading(self) -> None:
        """Reset every field to the between-titles loading state."""
        self._poster_targets.clear()
        self.main_poster_url = None
        self._heading_lbl.setText("Loading…")
        self._year_lbl.clear()
        self._clear_layout(self._meta_row)
        self._source_row_w.hide()
        self._clear_flow(self._genres_flow)
        self._genres_w.hide()
        self._overview_hdr.hide()
        self._plot_lbl.hide()
        self._plot_lbl.clear()
        self._cast_hdr.hide()
        self._cast_lbl.hide()
        self._cast_lbl.clear()
        self._versions_hdr.hide()
        self._versions_w.hide()
        self._clear_flow(self._versions_flow)
        self._similar_hdr_row_w.hide()
        self._strip_scroll.hide()
        self._clear_strip()
        self._poster.set_placeholder("…")
        self._like_btn.setChecked(False)
        self._dislike_btn.setChecked(False)
        self._not_interested_btn.setChecked(False)
        self._queue_btn.setText(f"{_icons.queue_icon} Queue")
        self._fav_btn.setText(f"{_icons.unfavorite_icon} Favorite")

    def show_error(self, message: str) -> None:
        """Reset to the loading skeleton and show a single error heading."""
        self.reset_loading()
        self._heading_lbl.setText(message)
        self._poster.set_placeholder("")

    def populate(self, data: dict) -> None:
        """Fill the card from a plain data dict (built off-thread by the overlay).

        Poster images are NOT loaded here — the overlay reads
        :meth:`pending_poster_urls` and pushes pixmaps back via
        :meth:`set_poster_pixmap` (QPixmap is main-thread only).
        """
        self._heading_lbl.setText(data.get("name") or "Unknown")
        year = data.get("year")
        self._year_lbl.setText(f"({year})" if year else "")

        self._populate_meta(data)
        self._populate_source(data)
        self._populate_genres(data.get("genres") or [])
        self._populate_rating(data)
        self._populate_actions(data)
        self._populate_overview(data.get("plot") or "")
        self._populate_cast(data.get("cast") or "")
        self._populate_versions(data.get("versions") or [])
        self._populate_similar(data.get("similar") or [])
        self._prepare_main_poster(data.get("poster_url"))

    def _populate_meta(self, data: dict) -> None:
        self._clear_layout(self._meta_row)
        parts: list[QLabel] = []
        rating = data.get("rating")
        if rating:
            star = QLabel(f"{_icons.rating_star_icon} {rating}")
            star.setStyleSheet(_theme.LIGHTBOX_STAR)
            parts.append(star)
        runtime = _fmt_runtime(data.get("runtime"))
        if runtime:
            parts.append(self._meta_text(runtime))
        mt = data.get("media_type") or ""
        icon = _MEDIA_TYPE_ICON.get(mt)
        if icon:
            parts.append(self._meta_text(f"{icon} {mt.title()}"))
        count = int(data.get("version_count") or 0)
        first = True
        for w in parts:
            if not first:
                self._meta_row.addWidget(self._meta_sep())
            self._meta_row.addWidget(w)
            first = False
        if count > 0:
            if not first:
                self._meta_row.addWidget(self._meta_sep())
            badge = QLabel(f"{_icons.variant_count_icon}{count} versions")
            badge.setStyleSheet(_theme.LIGHTBOX_VERSION_BADGE)
            badge.setToolTip(f"{count} other version(s) — see Other Versions below")
            self._meta_row.addWidget(badge)
        self._meta_row.addStretch()

    def _meta_text(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_theme.LIGHTBOX_META)
        return lbl

    def _meta_sep(self) -> QLabel:
        return self._meta_text("·")

    def _populate_source(self, data: dict) -> None:
        name = data.get("provider_name")
        if not name:
            self._source_row_w.hide()
            return
        active = bool(data.get("provider_active", True))
        dot_color = _theme.COLOR_OK if active else _theme.COLOR_MUTED
        self._source_dot.setStyleSheet(f"color: {dot_color}; font-size: {_theme.FONT_SM};")
        self._source_lbl.setText(f"Source: {name}")
        self._source_row_w.show()

    def _populate_genres(self, genres: list[str]) -> None:
        self._clear_flow(self._genres_flow)
        shown = 0
        for g in genres:
            g = (g or "").strip()
            if not g:
                continue
            chip = QLabel(g)
            chip.setStyleSheet(_theme.LIGHTBOX_GENRE_CHIP)
            self._genres_flow.addWidget(chip)
            shown += 1
        self._genres_w.setVisible(shown > 0)

    def _populate_rating(self, data: dict) -> None:
        rating = int(data.get("user_rating") or 0)
        self._like_btn.setChecked(rating > 0)
        self._dislike_btn.setChecked(rating < 0)
        self._not_interested_btn.setChecked(bool(data.get("is_suppressed")))

    def _populate_actions(self, data: dict) -> None:
        in_queue = bool(data.get("in_queue"))
        self._queue_btn.setText(
            f"{_icons.queue_icon} In Queue" if in_queue else f"{_icons.queue_icon} Queue"
        )
        is_fav = bool(data.get("is_favorite"))
        self._fav_btn.setText(
            f"{_icons.favorite_icon} Favorited" if is_fav
            else f"{_icons.unfavorite_icon} Favorite"
        )

    def _populate_overview(self, plot: str) -> None:
        has = bool(plot.strip())
        self._overview_hdr.setVisible(has)
        self._plot_lbl.setVisible(has)
        self._plot_lbl.setText(plot)

    def _populate_cast(self, cast: str) -> None:
        has = bool(cast.strip())
        self._cast_hdr.setVisible(has)
        self._cast_lbl.setVisible(has)
        self._cast_lbl.setText(cast)

    def _populate_versions(self, versions: list[dict]) -> None:
        self._clear_flow(self._versions_flow)
        if not versions:
            self._versions_hdr.hide()
            self._versions_w.hide()
            return
        self._versions_hdr.setText(f"OTHER VERSIONS ({len(versions)})")
        for v in versions:
            self._versions_flow.addWidget(self._make_version_chip(v))
        self._versions_hdr.show()
        self._versions_w.show()

    def _make_version_chip(self, v: dict) -> QPushButton:
        tag = v.get("tag") or ""
        name = v.get("name") or "?"
        src = v.get("provider_name") or ""
        label = f"{tag}  {name}" if tag else name
        if src:
            label += f"  · {src}"
        chip = QPushButton(label)
        chip.setFlat(True)
        chip.setStyleSheet(_theme.LIGHTBOX_VERSION_CHIP)
        chip.setToolTip(f"Preview this version: {name}")
        cid = v.get("id")
        chip.clicked.connect(lambda _=False, c=cid: self.dive_requested.emit(c))
        return chip

    def _populate_similar(self, similar: list[dict]) -> None:
        self._clear_strip()
        if not similar:
            self._similar_hdr_row_w.hide()
            self._strip_scroll.hide()
            return
        self._similar_hdr.setText(f"SIMILAR TITLES ({len(similar)})")
        for item in similar:
            card = self._make_sim_card(item)
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
        self._similar_hdr_row_w.show()
        self._strip_scroll.show()

    def _make_sim_card(self, item: dict) -> QWidget:
        cid = item.get("id")
        name = item.get("name") or "?"
        year = item.get("year")

        card = QWidget()
        col = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        poster_wrap = _ClickableFrame()
        poster_wrap.setObjectName("lightbox_sim_poster")
        poster_wrap.setFixedSize(_SIM_W, _SIM_H)
        poster_wrap.setStyleSheet(_theme.LIGHTBOX_SIM_POSTER)
        set_clickable(poster_wrap)
        poster_wrap.setToolTip(f"Preview in lightbox: {name}")
        # Whole poster is a dive-in target (mockup: "⤢ / click a card — dive in").
        poster_wrap.clicked.connect(lambda c=cid: self.dive_requested.emit(c))

        img = QLabel(poster_wrap)
        img.setGeometry(0, 0, _SIM_W, _SIM_H)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setWordWrap(True)
        img.setText(name)
        # Presses on the poster fall through to the clickable frame (dive-in).
        img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        expand = QPushButton(_icons.lightbox_icon, poster_wrap)
        expand.setFixedSize(26, 26)
        expand.move(_SIM_W - 32, 6)
        expand.setStyleSheet(_theme.LIGHTBOX_SIM_EXPAND_BTN)
        expand.setToolTip("Preview in lightbox")  # QPushButton auto-qualifies for the hand cursor
        expand.clicked.connect(lambda _=False, c=cid: self.dive_requested.emit(c))
        col.addWidget(poster_wrap)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(_theme.LIGHTBOX_SIM_NAME)
        name_lbl.setWordWrap(True)
        name_lbl.setFixedWidth(_SIM_W)
        col.addWidget(name_lbl)

        year_lbl = QLabel(str(year) if year else "")
        year_lbl.setStyleSheet(_theme.LIGHTBOX_SIM_YEAR)
        col.addWidget(year_lbl)

        url = item.get("poster_url")
        if url:
            self._poster_targets.setdefault(url, []).append(img)
        return card

    # ------------------------------------------------------------------ #
    # Poster image seam (overlay owns the ImageCache)                      #
    # ------------------------------------------------------------------ #

    def _prepare_main_poster(self, url: str | None) -> None:
        self.main_poster_url = url or None
        if url:
            self._poster.set_placeholder("")
            self._poster_targets.setdefault(url, [])  # marker; main handled specially
        else:
            self._poster.set_placeholder("No poster")

    def pending_poster_urls(self) -> list[str]:
        """URLs the overlay should load (main poster + strip cards), main first."""
        urls: list[str] = []
        if self.main_poster_url:
            urls.append(self.main_poster_url)
        for u in self._poster_targets:
            if u != self.main_poster_url:
                urls.append(u)
        return urls

    def set_poster_pixmap(self, url: str, pix: QPixmap) -> None:
        """Route a loaded pixmap to the main poster and/or any strip cards."""
        if url == self.main_poster_url:
            self._poster.set_pixmap(pix)
        for lbl in self._poster_targets.get(url, []):
            scaled = pix.scaled(
                QSize(_SIM_W, _SIM_H),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl.setPixmap(scaled)
            lbl.setText("")

    # ------------------------------------------------------------------ #
    # Layout helpers                                                       #
    # ------------------------------------------------------------------ #

    def _clear_strip(self) -> None:
        # Keep the trailing stretch (index count-1); remove card widgets before it.
        while self._strip_layout.count() > 1:
            item = self._strip_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    @staticmethod
    def _clear_flow(flow) -> None:
        while flow.count():
            item = flow.takeAt(0)
            if item is not None and (w := item.widget()):
                w.deleteLater()
