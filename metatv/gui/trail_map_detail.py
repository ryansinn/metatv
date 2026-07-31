"""The Explore trail-map's bottom detail strip (a dumb view).

Tracks the row selected in the columns above and shows the rich, one-authoritative
card for that title: poster (click → poster lightbox) with a corner "mark watched"
badge, title + year + a persistent favourite title-star, a meta line (★rating ·
runtime · language · watch stats), Overview + Cast + Director shown **only-if-
available** (good-on-raw-data), and on the right a single big **Play / Resume /
Play again** button driven by the 3-state watch model, a secondary 👍👎🙅📋 row,
**↗ Open in details** and **✦ Make recipe**.

It emits parameterless intents; :class:`~metatv.gui.trail_map_view.TrailMapView`
attaches the selected channel id and relays them to the existing host handlers.
Rich metadata (overview/cast/director/runtime) arrives asynchronously via
:meth:`set_metadata` — the host fetches it through ``metadata_manager.get_metadata``
(the same 3-tier seam the details pane uses).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable
from metatv.gui.sentiment_bar import SentimentBar
from metatv.gui.trail_map_data import TrailRowDTO

_DPOSTER_W, _DPOSTER_H = 104, 156


def _fmt_runtime(minutes: int | None) -> str:
    if not minutes or minutes <= 0:
        return ""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def _fmt_resume(seconds: int) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def watch_state(row: TrailRowDTO) -> str:
    """Classify a row into the 3 watch states that drive the Play label + badge.

    ``"done"`` (completed) → Play again; ``"partial"`` (a resume target — progress
    saved, not completed) → Resume M:SS; ``"none"`` → Play.  A completed movie has
    its progress cleared, so it is Play-again, not Resume.
    """
    if row.watch_completed:
        return "done"
    if row.watch_progress > 0:
        return "partial"
    return "none"


class _DetailPoster(QFrame):
    """Poster surface: click expands (poster lightbox); corner badge marks watched."""

    clicked         = pyqtSignal()
    watched_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trailmap_detail_poster")
        self.setFixedSize(_DPOSTER_W, _DPOSTER_H)
        self.setStyleSheet(_theme.TRAILMAP_DETAIL_POSTER)
        set_clickable(self)
        self.setToolTip("Click to enlarge the poster")

        self._img = QLabel(self)
        self._img.setGeometry(0, 0, _DPOSTER_W, _DPOSTER_H)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setWordWrap(True)
        self._img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._wbadge = QPushButton(_icons.unwatched_icon, self)
        self._wbadge.setFixedSize(22, 22)
        self._wbadge.move(6, 6)
        self._wbadge.clicked.connect(self.watched_clicked)  # QPushButton → hand cursor for free

    def set_pixmap(self, pix: QPixmap) -> None:
        self._img.setPixmap(pix.scaled(
            QSize(_DPOSTER_W, _DPOSTER_H),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self._img.setText("")

    def set_placeholder(self, text: str) -> None:
        self._img.setPixmap(QPixmap())
        self._img.setText(text)

    def set_watch_state(self, state: str) -> None:
        glyph, style, tip = {
            "done": (_icons.watched_icon, _theme.TRAILMAP_WBADGE_DONE,
                     "Watched — click to unmark"),
            "partial": (_icons.partial_watched_icon, _theme.TRAILMAP_WBADGE_PARTIAL,
                        "Partially watched — click to mark done"),
        }.get(state, (_icons.unwatched_icon, _theme.TRAILMAP_WBADGE, "Mark as watched"))
        self._wbadge.setText(glyph)
        self._wbadge.setStyleSheet(style)
        self._wbadge.setToolTip(tip)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


class TrailDetailStrip(QWidget):
    """The selected-title detail strip beneath the trail-map columns."""

    play_requested      = pyqtSignal()
    resume_requested    = pyqtSignal()
    rating_clicked      = pyqtSignal(int)
    suppression_toggled = pyqtSignal(bool)
    queue_clicked       = pyqtSignal()
    favorite_clicked    = pyqtSignal()
    watched_toggled     = pyqtSignal(bool)   # True → mark watched, False → unmark
    open_details_clicked = pyqtSignal()
    recipe_clicked      = pyqtSignal()
    poster_expand_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trailmap_detail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_theme.TRAILMAP_DETAIL)

        self._row: TrailRowDTO | None = None
        self._can_resume = False
        self.poster_url: str | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(16)
        self._build_poster(outer)
        self._build_body(outer)
        self._build_side(outer)
        self._show_empty()

    # -- construction ----------------------------------------------------- #
    def _build_poster(self, outer: QHBoxLayout) -> None:
        self._poster = _DetailPoster()
        self._poster.clicked.connect(self.poster_expand_clicked)
        self._poster.watched_clicked.connect(self._on_watched_badge)
        outer.addWidget(self._poster, 0, Qt.AlignmentFlag.AlignTop)

    def _build_body(self, outer: QHBoxLayout) -> None:
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(_theme.TRAILMAP_DETAIL_TITLE)
        title_row.addWidget(self._title_lbl, 0)
        self._year_lbl = QLabel()
        self._year_lbl.setStyleSheet(_theme.TRAILMAP_DETAIL_YEAR)
        title_row.addWidget(self._year_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        self._fav_star = QPushButton(_icons.unfavorite_icon)
        self._fav_star.setCheckable(True)
        self._fav_star.setFlat(True)
        self._fav_star.setFixedSize(30, 30)
        self._fav_star.setStyleSheet(_theme.TRAILMAP_FAV_STAR)
        self._fav_star.clicked.connect(self._on_fav_clicked)
        title_row.addWidget(self._fav_star, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()
        body.addLayout(title_row)

        self._meta_row_w = QWidget()
        self._meta_row = QHBoxLayout(self._meta_row_w)
        self._meta_row.setContentsMargins(0, 0, 0, 0)
        self._meta_row.setSpacing(8)
        body.addWidget(self._meta_row_w)

        self._overview_lbl = QLabel()
        self._overview_lbl.setWordWrap(True)
        self._overview_lbl.setStyleSheet(_theme.TRAILMAP_OVERVIEW)
        body.addWidget(self._overview_lbl)

        self._crew_lbl = QLabel()
        self._crew_lbl.setWordWrap(True)
        self._crew_lbl.setStyleSheet(_theme.TRAILMAP_CREW)
        body.addWidget(self._crew_lbl)

        body.addStretch()
        body_w = QWidget()
        body_w.setLayout(body)
        body_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(body_w, 1)

    def _build_side(self, outer: QHBoxLayout) -> None:
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(7)
        side.addStretch()

        self._play_btn = QPushButton()
        self._play_btn.setStyleSheet(_theme.TRAILMAP_PLAY_BTN)
        self._play_btn.clicked.connect(self._on_play_clicked)
        side.addWidget(self._play_btn)

        self._sentiment = SentimentBar(btn_size=30)
        self._sentiment.rating_clicked.connect(self.rating_clicked)
        self._sentiment.suppression_toggled.connect(self.suppression_toggled)
        self._sentiment.queue_clicked.connect(self.queue_clicked)
        side.addWidget(self._sentiment, 0, Qt.AlignmentFlag.AlignHCenter)

        self._open_btn = QPushButton(f"{_icons.see_all_arrow_icon} Open in details")
        self._open_btn.setStyleSheet(_theme.TRAILMAP_DETAIL_LINK_BTN)
        self._open_btn.setToolTip("Open this title in the main details pane")
        self._open_btn.clicked.connect(self.open_details_clicked)
        side.addWidget(self._open_btn)

        self._recipe_btn = QPushButton(f"{_icons.recipe_icon} Make recipe")
        self._recipe_btn.setStyleSheet(_theme.TRAILMAP_DETAIL_LINK_BTN)
        self._recipe_btn.setToolTip("Build a recipe from this title's genre & tags")
        self._recipe_btn.clicked.connect(self.recipe_clicked)
        side.addWidget(self._recipe_btn)

        side.addStretch()
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(168)
        outer.addWidget(side_w, 0)

    # -- population ------------------------------------------------------- #
    def _show_empty(self) -> None:
        self._row = None
        self.poster_url = None
        self._poster.set_placeholder("")
        self._poster.set_watch_state("none")
        self._title_lbl.setText("Select a title")
        self._year_lbl.clear()
        self._fav_star.setChecked(False)
        self._fav_star.setText(_icons.unfavorite_icon)
        self._clear_meta()
        self._overview_lbl.setText("Pick any stop or similar title above to see its details here.")
        self._overview_lbl.setStyleSheet(_theme.TRAILMAP_EMPTY_HINT)
        self._crew_lbl.hide()
        self._play_btn.setText(f"{_icons.play_icon} Play")
        self._play_btn.setEnabled(False)
        self._sentiment.setEnabled(False)
        self._open_btn.setEnabled(False)
        self._recipe_btn.setEnabled(False)

    def populate(self, row: TrailRowDTO) -> None:
        """Fill the strip from a cached row DTO (rich metadata arrives via set_metadata)."""
        self._row = row
        self.poster_url = row.poster_url
        self._poster.set_placeholder("" if row.poster_url else "No poster")
        self._poster.set_watch_state(watch_state(row))

        self._title_lbl.setText(row.title or "Unknown")
        self._year_lbl.setText(f"({row.year})" if row.year else "")
        self._fav_star.setChecked(row.is_favorite)
        self._fav_star.setText(_icons.favorite_icon if row.is_favorite else _icons.unfavorite_icon)
        self._fav_star.setToolTip(
            "Remove from Favorites" if row.is_favorite else "Add to Favorites"
        )

        self._sentiment.setEnabled(True)
        self._sentiment.set_state(
            user_rating=row.user_rating, is_suppressed=row.is_suppressed, in_queue=row.in_queue,
        )
        self._open_btn.setEnabled(True)
        self._recipe_btn.setEnabled(True)
        self._play_btn.setEnabled(True)

        # Meta + overview/crew render from the row now; set_metadata enriches them.
        self._render_meta(row, detail={})
        self._apply_play_label(row)
        self._overview_lbl.setStyleSheet(_theme.TRAILMAP_OVERVIEW)
        self._overview_lbl.setText("")
        self._overview_lbl.hide()
        self._crew_lbl.hide()

    def set_metadata(self, row_id: str, detail: dict) -> None:
        """Enrich the strip with on-demand metadata (overview / cast / director / runtime).

        Guarded by *row_id* so a late fetch for a since-deselected title is dropped.
        Fields render only-if-available (good-on-raw-data).
        """
        if not self._row or self._row.id != row_id:
            return
        self._render_meta(self._row, detail)
        plot = (detail.get("plot") or "").strip()
        self._overview_lbl.setStyleSheet(_theme.TRAILMAP_OVERVIEW)
        self._overview_lbl.setText(plot)
        self._overview_lbl.setVisible(bool(plot))

        cast = (detail.get("cast") or "").strip()
        director = (detail.get("director") or "").strip()
        parts = []
        if cast:
            parts.append(cast)
        if director:
            parts.append(f"dir. {director}")
        crew = "  ·  ".join(parts)
        self._crew_lbl.setText(crew)
        self._crew_lbl.setVisible(bool(crew))

    # -- poster image seam (host owns the ImageCache) --------------------- #
    def set_poster_pixmap(self, pix: QPixmap) -> None:
        self._poster.set_pixmap(pix)

    # -- helpers ---------------------------------------------------------- #
    def _clear_meta(self) -> None:
        while self._meta_row.count():
            item = self._meta_row.takeAt(0)
            if w := item.widget():
                # setParent(None) removes the old label from view immediately —
                # deleteLater alone leaves it painted (a stretched ghost) until the
                # event loop runs, since populate() then set_metadata() both rebuild here.
                w.setParent(None)
                w.deleteLater()

    def _meta_text(self, text: str, style: str = _theme.TRAILMAP_DETAIL_META) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _render_meta(self, row: TrailRowDTO, detail: dict) -> None:
        self._clear_meta()
        parts: list[QLabel] = []
        rating = detail.get("rating") or row.rating
        if rating:
            parts.append(self._meta_text(
                f"{_icons.rating_star_icon} {rating}", _theme.TRAILMAP_DETAIL_STAR
            ))
        runtime = _fmt_runtime(detail.get("runtime"))
        if runtime:
            parts.append(self._meta_text(runtime))
        if row.lang:
            chip = QLabel(row.lang)
            chip.setStyleSheet(_theme.LANG_CHIP)   # shared canonical lang/region chip
            chip.setToolTip(f"Language / region: {row.lang}")
            parts.append(chip)
        if row.watch_count:
            parts.append(self._meta_text(
                f"watched {row.watch_count}×"
                + (f" · {row.last_watched}" if row.last_watched else "")
            ))
        first = True
        for w in parts:
            if not first:
                self._meta_row.addWidget(self._meta_text("·"))
            self._meta_row.addWidget(w)
            first = False
        self._meta_row.addStretch()

    def _apply_play_label(self, row: TrailRowDTO) -> None:
        state = watch_state(row)
        if state == "partial":
            self._can_resume = True
            self._play_btn.setText(f"{_icons.play_icon} Resume {_fmt_resume(row.watch_progress)}")
            self._play_btn.setToolTip("Resume from where you left off")
        elif state == "done":
            self._can_resume = False
            self._play_btn.setText(f"{_icons.play_icon} Play again")
            self._play_btn.setToolTip("Play again from the beginning")
        else:
            self._can_resume = False
            self._play_btn.setText(f"{_icons.play_icon} Play")
            self._play_btn.setToolTip("Play from the beginning")

    # -- click handlers --------------------------------------------------- #
    def _on_play_clicked(self) -> None:
        if self._can_resume:
            self.resume_requested.emit()
        else:
            self.play_requested.emit()

    def _on_fav_clicked(self) -> None:
        # Optimistic swap; the host persists and a reload re-syncs.
        on = self._fav_star.isChecked()
        self._fav_star.setText(_icons.favorite_icon if on else _icons.unfavorite_icon)
        self.favorite_clicked.emit()

    def _on_watched_badge(self) -> None:
        if not self._row:
            return
        currently_done = watch_state(self._row) == "done"
        self.watched_toggled.emit(not currently_done)
