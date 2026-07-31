"""Lightbox overlay for browsing similar titles without leaving the current details pane.

Opening a Similar Titles row (right-click, or the ⤢ preview button) raises this
poster-hero overlay. The user can browse the origin's similar list with the
prev/next chevrons, dive deeper into any similar title or Other Version
(rabbit-hole with a Back step), and close to return to the untouched details pane.

Architecture:
- ``SimilarTitleLightbox`` (this file) is a child QWidget of the main window,
  raised above everything via ``raise_()``. It owns the backdrop, the prev/next
  chevrons flanking the card, the navigation state, the background DB read
  (``_bg_load``) and the ImageCache. It is intentionally thin.
- ``_LightboxCard`` (``similar_lightbox_card.py``) owns the card's widget tree and
  populate logic. It emits user intents as signals; this overlay attaches the
  current channel id and relays them to the main window (the existing external
  play/queue/favorite/rating/suppress/hide paths — unchanged signatures).
- Background DB reads marshal results back via the ``_data_ready`` signal (never a
  QTimer from a worker thread); QPixmaps are only ever built on the main thread.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.similar_lightbox_card import _LightboxCard

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.image_cache import ImageCache


class SimilarTitleLightbox(QWidget):
    """Full-window overlay that previews a similar title without replacing the details pane."""

    play_requested        = pyqtSignal(str)       # channel_id
    queue_toggled         = pyqtSignal(str)
    favorite_toggled      = pyqtSignal(str)
    hide_requested        = pyqtSignal(str)
    rating_requested      = pyqtSignal(str, int)  # channel_id, ±1
    suppression_requested = pyqtSignal(str, bool) # channel_id, suppressed

    # Internal signal — background thread emits this; main thread receives it
    _data_ready = pyqtSignal(str, object)   # channel_id, data dict

    def __init__(
        self,
        parent: QWidget,
        config: "Config",
        image_cache: "ImageCache",
        db: "Database",
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._image_cache = image_cache
        self._db = db
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lightbox")

        # Navigation state
        self._origin_ids: list[str] = []
        self._origin_idx: int = 0
        self._origin_title: str = ""
        self._nav_stack: list[str] = []
        self._current_id: str = ""

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._data_ready.connect(self._apply_data)
        self._image_cache.image_loaded.connect(self._on_image_loaded)
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def show_preview(
        self,
        channel_ids: list[str],
        index: int,
        origin_title: str,
    ) -> None:
        """Open (or refresh) the lightbox at channel_ids[index]."""
        if not channel_ids:
            return
        self._origin_ids = list(channel_ids)
        self._origin_idx = max(0, min(index, len(channel_ids) - 1))
        self._origin_title = origin_title
        self._nav_stack = []
        self._card.set_header(origin_title)
        self._card.set_back_visible(False)
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()
        self._load_channel(channel_ids[self._origin_idx])

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._prev_chev = self._make_chevron(_icons.nav_prev_icon, "Previous similar title (←)")
        self._prev_chev.clicked.connect(self._go_prev)
        row.addWidget(self._prev_chev, 0, Qt.AlignmentFlag.AlignVCenter)

        self._card = _LightboxCard()
        self._card.back_clicked.connect(self._go_back)
        self._card.close_clicked.connect(self._close)
        self._card.play_clicked.connect(lambda: self.play_requested.emit(self._current_id))
        self._card.queue_clicked.connect(lambda: self.queue_toggled.emit(self._current_id))
        self._card.favorite_clicked.connect(lambda: self.favorite_toggled.emit(self._current_id))
        self._card.hide_clicked.connect(lambda: self.hide_requested.emit(self._current_id))
        self._card.rating_clicked.connect(lambda r: self.rating_requested.emit(self._current_id, r))
        self._card.suppression_toggled.connect(
            lambda on: self.suppression_requested.emit(self._current_id, on)
        )
        self._card.dive_requested.connect(self._dive_into)
        row.addWidget(self._card, 0, Qt.AlignmentFlag.AlignVCenter)

        self._next_chev = self._make_chevron(_icons.nav_next_icon, "Next similar title (→)")
        self._next_chev.clicked.connect(self._go_next)
        row.addWidget(self._next_chev, 0, Qt.AlignmentFlag.AlignVCenter)

        row_w = QWidget()
        row_w.setLayout(row)
        outer.addWidget(row_w)

    def _make_chevron(self, glyph: str, tip: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setFixedSize(44, 44)
        btn.setFlat(True)
        btn.setStyleSheet(_theme.LIGHTBOX_CHEVRON)
        btn.setToolTip(tip)
        return btn

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def _load_channel(self, channel_id: str) -> None:
        self._current_id = channel_id
        self._update_nav_state()
        self._card.reset_loading()
        self._executor.submit(self._bg_load, channel_id)

    def _bg_load(self, channel_id: str) -> None:
        """Background: fetch channel + metadata + siblings from DB, emit _data_ready.

        Runs off the UI thread. Reads only ``self._db`` / ``self._config`` and emits
        ``self._data_ready`` — never touches Qt widgets or the ImageCache (poster
        pixmaps are built on the main thread in ``_apply_data``). Uses
        ``session_scope`` and returns a plain dict (no ORM object escapes the block).
        """
        from metatv.core.database import ChannelDB, MetadataDB, ProviderDB
        from metatv.core.repositories import RepositoryFactory

        data: dict = {}
        try:
            with self._db.session_scope(commit=False) as session:
                ch = session.get(ChannelDB, channel_id)
                if not ch:
                    self._data_ready.emit(channel_id, {})
                    return

                repos = RepositoryFactory(session)
                # Absolute gate (DR-0007): hidden = inactive ∪ expired ∪ orphaned.
                hidden = set(repos.providers.get_hidden_provider_ids())
                provider = session.get(ProviderDB, ch.provider_id) if ch.provider_id else None
                provider_name = provider.name if provider else None
                provider_active = bool(ch.provider_id) and ch.provider_id not in hidden

                meta = session.get(MetadataDB, ch.metadata_id) if ch.metadata_id else None

                # Similar titles — canonical scoped chokepoint (shared with the
                # details-pane row): owns candidate selection, content_key dedup and
                # the visibility gate. We hydrate lightweight display dicts per row.
                similar: list[dict] = []
                for c in repos.channels.get_similar_channels(
                    channel_id, excluded_provider_ids=hidden, limit=12, config=self._config,
                ):
                    c_meta = (
                        session.get(MetadataDB, c.metadata_id) if c.metadata_id else None
                    )
                    similar.append({
                        "id": c.id,
                        "name": c.detected_title or c.name,
                        "year": (c_meta.year if c_meta else None) or c.detected_year,
                        "poster_url": c_meta.poster_url if c_meta else None,
                        "media_type": c.media_type or "",
                    })

                # Other Versions — stored content_key siblings, provider-scoped with
                # the SAME gate (hidden/expired sources never surface here either).
                versions: list[dict] = []
                if ch.content_key:
                    for s in repos.channels.get_content_key_siblings(
                        ch.content_key, channel_id, excluded_provider_ids=hidden,
                    ):
                        tag = (
                            s.get("detected_quality")
                            or s.get("detected_region")
                            or s.get("detected_prefix")
                            or ""
                        )
                        versions.append({
                            "id": s["id"],
                            "name": s.get("name") or "?",
                            "tag": tag,
                            "provider_name": s.get("provider_name"),
                        })

                data = {
                    "id": channel_id,
                    "name": ch.detected_title or ch.name,
                    "media_type": ch.media_type or "",
                    "provider_name": provider_name,
                    "provider_active": provider_active,
                    "is_favorite": bool(ch.is_favorite),
                    "is_hidden": bool(ch.is_hidden),
                    "in_queue": repos.queue.is_queued(channel_id),
                    # Real like/dislike from UserRatingDB, real suppression from the
                    # ChannelDB.is_rec_suppressed column (the old getattr(ch,
                    # "user_rating"/"is_suppressed") read columns that don't exist, so
                    # the buttons never lit up).
                    "user_rating": repos.ratings.get(channel_id) or 0,
                    "is_suppressed": bool(ch.is_rec_suppressed),
                    "poster_url": meta.poster_url if meta else None,
                    "year": (meta.year if meta else None) or ch.detected_year,
                    "rating": meta.rating if meta else None,
                    "runtime": meta.runtime if meta else None,
                    "genres": self._extract_genres(meta),
                    "plot": meta.plot if meta else None,
                    "cast": self._extract_cast(meta),
                    "similar": similar,
                    "versions": versions,
                    "version_count": len(versions),
                }
        except Exception:
            logger.exception("Lightbox bg_load failed for %s", channel_id)
            data = {}

        # Signal is thread-safe — Qt queues delivery to the main thread
        self._data_ready.emit(channel_id, data)

    @staticmethod
    def _extract_genres(meta) -> list[str]:
        """Normalize MetadataDB.genres (JSON list, or a legacy comma string) → list."""
        if not meta:
            return []
        raw = getattr(meta, "genres", None)
        if isinstance(raw, list):
            return [str(g).strip() for g in raw if str(g).strip()]
        if isinstance(raw, str):
            return [g.strip() for g in raw.split(",") if g.strip()]
        return []

    @staticmethod
    def _extract_cast(meta) -> str:
        """Build a 'A, B, C · dir. D' line from MetadataDB cast + director."""
        if not meta:
            return ""
        names = [
            (p.get("name") or "")
            for p in (getattr(meta, "cast", None) or [])[:5]
            if isinstance(p, dict)
        ]
        cast = ", ".join(n for n in names if n)
        director = (getattr(meta, "director", None) or "").strip()
        if director:
            return f"{cast} · dir. {director}" if cast else f"dir. {director}"
        return cast

    def _apply_data(self, channel_id: str, data: object) -> None:
        """Called on the main thread via _data_ready signal."""
        if channel_id != self._current_id or not self.isVisible():
            return
        if not isinstance(data, dict) or not data:
            self._card.show_error("Could not load details")
            return

        self._card.populate(data)

        # Poster images — main thread only. Check the sync cache first, fall back
        # to async (the shared image_loaded slot routes results back to the card).
        for url in self._card.pending_poster_urls():
            pix = self._image_cache.get_image_sync(url)
            if pix:
                self._card.set_poster_pixmap(url, pix)
            else:
                self._image_cache.get_image_async(url)

    def _on_image_loaded(self, url: str, pix: QPixmap) -> None:
        if self.isVisible():
            self._card.set_poster_pixmap(url, pix)

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    def _go_prev(self) -> None:
        if self._nav_stack:
            return
        self._origin_idx = max(0, self._origin_idx - 1)
        self._load_channel(self._origin_ids[self._origin_idx])

    def _go_next(self) -> None:
        if self._nav_stack:
            return
        self._origin_idx = min(len(self._origin_ids) - 1, self._origin_idx + 1)
        self._load_channel(self._origin_ids[self._origin_idx])

    def _dive_into(self, channel_id: str) -> None:
        """Navigate deeper into similar / other-version content (rabbit-hole mode)."""
        if not channel_id:
            return
        self._nav_stack.append(self._current_id)
        self._card.set_back_visible(True)
        self._load_channel(channel_id)

    def _go_back(self) -> None:
        if not self._nav_stack:
            return
        prev_id = self._nav_stack.pop()
        if not self._nav_stack:
            self._card.set_back_visible(False)
        self._load_channel(prev_id)

    def _update_nav_state(self) -> None:
        in_rabbit_hole = bool(self._nav_stack)
        n = len(self._origin_ids)
        if in_rabbit_hole:
            self._card.set_counter("")
            self._prev_chev.setEnabled(False)
            self._next_chev.setEnabled(False)
        else:
            idx = self._origin_idx
            self._card.set_counter(f"{idx + 1} of {n}")
            self._prev_chev.setEnabled(idx > 0)
            self._next_chev.setEnabled(idx < n - 1)

    # ------------------------------------------------------------------ #
    # Dismiss                                                              #
    # ------------------------------------------------------------------ #

    def _close(self) -> None:
        self._nav_stack.clear()
        self._card.set_back_visible(False)
        self.hide()

    def mousePressEvent(self, event) -> None:
        # Close only on a genuine backdrop click. A press on the card (incl. its
        # padding) or a chevron is a control interaction — walk up from the widget
        # under the cursor and bail if the card/chevron is an ancestor.
        node = self.childAt(event.pos())
        while node is not None:
            if node in (self._card, self._prev_chev, self._next_chev):
                super().mousePressEvent(event)
                return
            node = node.parent()
        self._close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close()
        elif event.key() == Qt.Key.Key_Left and not self._nav_stack:
            self._go_prev()
        elif event.key() == Qt.Key.Key_Right and not self._nav_stack:
            self._go_next()
        elif event.key() == Qt.Key.Key_Backspace and self._nav_stack:
            self._go_back()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    # Backdrop rendering                                                   #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 185))
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._card.setMaximumHeight(max(420, int(self.height() * 0.9)))
