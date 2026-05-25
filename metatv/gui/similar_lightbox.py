"""Lightbox overlay for browsing similar titles without leaving the current details pane.

Right-clicking a Similar Titles row opens this overlay. The user can browse deeper
into similar content — each title's details load inside the lightbox — and then
close it to return to the original channel's details pane untouched.

Architecture:
- SimilarTitleLightbox is a child QWidget of the main window, raised above all other
  widgets via raise_(). It covers the full main-window area.
- paintEvent draws a semi-transparent backdrop. Clicks on the backdrop dismiss it.
- The content card is a centred QFrame containing the full preview.
- Internal navigation is tracked via a simple stack so the user can go back.
- Left/right arrows cycle the original similar-titles list from the calling context.
- Background DB reads marshal results back via _data_ready signal (never QTimer from threads).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

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
        self._origin_ids = list(channel_ids)
        self._origin_idx = max(0, min(index, len(channel_ids) - 1))
        self._origin_title = origin_title
        self._nav_stack = []
        self._header_lbl.setText(f"Similar Titles to:  {origin_title}")
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

        self._card = QFrame()
        self._card.setObjectName("lightbox_card")
        self._card.setStyleSheet(
            "#lightbox_card { background: #1e1e2e; border-radius: 10px;"
            " border: 1px solid #444; }"
        )
        self._card.setFixedWidth(760)
        self._card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        self._card.setMaximumHeight(640)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ---- header bar ----
        header_bar = QWidget()
        header_bar.setStyleSheet("background: #2a2a3e; border-radius: 10px 10px 0 0;")
        header_row = QHBoxLayout(header_bar)
        header_row.setContentsMargins(14, 8, 10, 8)
        header_row.setSpacing(8)

        self._back_btn = QPushButton("◀ Back")
        self._back_btn.setFlat(True)
        self._back_btn.setStyleSheet("color: #8aacf7; font-size: 12px; border: none;")
        self._back_btn.setToolTip("Go back to previous title")
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.hide()
        header_row.addWidget(self._back_btn)

        self._header_lbl = QLabel()
        self._header_lbl.setStyleSheet("color: #ccc; font-size: 12px; font-weight: bold;")
        header_row.addWidget(self._header_lbl, 1)

        self._counter_lbl = QLabel()
        self._counter_lbl.setStyleSheet("color: #888; font-size: 11px;")
        header_row.addWidget(self._counter_lbl)

        close_btn = QPushButton(self._config.close_icon)
        close_btn.setFlat(True)
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet("color: #888; font-size: 14px; border: none;")
        close_btn.setToolTip("Close preview")
        close_btn.clicked.connect(self._close)
        header_row.addWidget(close_btn)

        card_layout.addWidget(header_bar)

        # ---- navigation row (prev / content / next) ----
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(0)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(36)
        self._prev_btn.setFlat(True)
        self._prev_btn.setStyleSheet(
            "QPushButton { color: #888; font-size: 18px; border: none; }"
            "QPushButton:hover { color: #fff; }"
            "QPushButton:disabled { color: #333; }"
        )
        self._prev_btn.setToolTip("Previous similar title")
        self._prev_btn.clicked.connect(self._go_prev)
        nav_row.addWidget(self._prev_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(8)
        self._build_content_widgets()

        scroll.setWidget(self._content_widget)
        nav_row.addWidget(scroll, 1)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(36)
        self._next_btn.setFlat(True)
        self._next_btn.setStyleSheet(
            "QPushButton { color: #888; font-size: 18px; border: none; }"
            "QPushButton:hover { color: #fff; }"
            "QPushButton:disabled { color: #333; }"
        )
        self._next_btn.setToolTip("Next similar title")
        self._next_btn.clicked.connect(self._go_next)
        nav_row.addWidget(self._next_btn)

        nav_widget = QWidget()
        nav_widget.setLayout(nav_row)
        card_layout.addWidget(nav_widget, 1)

        outer.addWidget(self._card)

    def _build_content_widgets(self) -> None:
        """Build the inner content panel (poster + metadata + plot + cast + buttons)."""
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self._poster_lbl = QLabel()
        self._poster_lbl.setFixedSize(110, 160)
        self._poster_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._poster_lbl.setStyleSheet(
            "background: #111; border-radius: 4px; color: #555; font-size: 10px;"
        )
        top_row.addWidget(self._poster_lbl)

        right_col = QVBoxLayout()
        right_col.setSpacing(4)

        self._title_lbl = QLabel()
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #eee;")
        right_col.addWidget(self._title_lbl)

        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet("font-size: 11px; color: #888;")
        right_col.addWidget(self._meta_lbl)

        self._source_lbl = QLabel()
        self._source_lbl.setStyleSheet("font-size: 11px; color: #666;")
        right_col.addWidget(self._source_lbl)

        self._genres_lbl = QLabel()
        self._genres_lbl.setWordWrap(True)
        self._genres_lbl.setStyleSheet("font-size: 11px; color: lightblue;")
        right_col.addWidget(self._genres_lbl)

        # Rating buttons (Like / Not Interested / Dislike)
        _RATING_STYLE = (
            "QPushButton { border: none; border-radius: 3px; padding: 2px 6px;"
            " font-size: 13px; color: #888; }"
            "QPushButton:checked { background: rgba(255,255,255,0.18); color: #fff; }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); color: #ccc; }"
        )
        rating_row = QHBoxLayout()
        rating_row.setSpacing(4)
        rating_row.setContentsMargins(0, 0, 0, 0)

        self._like_btn = QPushButton(self._config.like_icon)
        self._like_btn.setCheckable(True)
        self._like_btn.setFixedSize(30, 24)
        self._like_btn.setFlat(True)
        self._like_btn.setToolTip("Like")
        self._like_btn.setStyleSheet(_RATING_STYLE)
        self._like_btn.clicked.connect(lambda: self.rating_requested.emit(self._current_id, 1))
        rating_row.addWidget(self._like_btn)

        self._not_interested_btn = QPushButton(self._config.not_interested_icon)
        self._not_interested_btn.setCheckable(True)
        self._not_interested_btn.setFixedSize(30, 24)
        self._not_interested_btn.setFlat(True)
        self._not_interested_btn.setToolTip("Not Interested (suppress from recommendations)")
        self._not_interested_btn.setStyleSheet(_RATING_STYLE)
        self._not_interested_btn.clicked.connect(
            lambda checked: self.suppression_requested.emit(self._current_id, checked)
        )
        rating_row.addWidget(self._not_interested_btn)

        self._dislike_btn = QPushButton(self._config.dislike_icon)
        self._dislike_btn.setCheckable(True)
        self._dislike_btn.setFixedSize(30, 24)
        self._dislike_btn.setFlat(True)
        self._dislike_btn.setToolTip("Dislike")
        self._dislike_btn.setStyleSheet(_RATING_STYLE)
        self._dislike_btn.clicked.connect(lambda: self.rating_requested.emit(self._current_id, -1))
        rating_row.addWidget(self._dislike_btn)

        rating_row.addStretch()
        right_col.addLayout(rating_row)
        right_col.addStretch()

        # Watch / library action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._play_btn = QPushButton(f"{self._config.play_icon} Play")
        self._play_btn.setToolTip("Play this title")
        self._play_btn.clicked.connect(lambda: self.play_requested.emit(self._current_id))
        btn_row.addWidget(self._play_btn)

        self._queue_btn = QPushButton(f"{self._config.queue_icon} Queue")
        self._queue_btn.setToolTip("Add to / remove from Watch Queue")
        self._queue_btn.clicked.connect(lambda: self.queue_toggled.emit(self._current_id))
        btn_row.addWidget(self._queue_btn)

        self._fav_btn = QPushButton(f"{self._config.unfavorite_icon} Favorite")
        self._fav_btn.setToolTip("Add to / remove from Favorites")
        self._fav_btn.clicked.connect(lambda: self.favorite_toggled.emit(self._current_id))
        btn_row.addWidget(self._fav_btn)

        self._hide_btn = QPushButton(f"{self._config.hide_icon} Hide")
        self._hide_btn.setToolTip("Hide this channel from all views")
        self._hide_btn.clicked.connect(lambda: self.hide_requested.emit(self._current_id))
        btn_row.addWidget(self._hide_btn)

        right_col.addLayout(btn_row)
        top_row.addLayout(right_col, 1)
        self._content_layout.addLayout(top_row)

        # Overview section
        overview_hdr = QLabel("Overview")
        overview_hdr.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #999; margin-top: 6px;"
        )
        self._content_layout.addWidget(overview_hdr)

        self._plot_lbl = QLabel()
        self._plot_lbl.setWordWrap(True)
        self._plot_lbl.setStyleSheet("font-size: 12px; color: #ccc;")
        self._content_layout.addWidget(self._plot_lbl)

        # Cast & Crew section
        cast_hdr = QLabel("Cast & Crew")
        cast_hdr.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #999; margin-top: 4px;"
        )
        self._content_layout.addWidget(cast_hdr)

        self._cast_lbl = QLabel()
        self._cast_lbl.setWordWrap(True)
        self._cast_lbl.setStyleSheet("font-size: 11px; color: #888;")
        self._content_layout.addWidget(self._cast_lbl)

        self._similar_header_lbl = QLabel("Similar Titles:")
        self._similar_header_lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #888; margin-top: 6px;"
        )
        self._similar_header_lbl.hide()
        self._content_layout.addWidget(self._similar_header_lbl)

        self._similar_container = QWidget()
        self._similar_vbox = QVBoxLayout(self._similar_container)
        self._similar_vbox.setContentsMargins(0, 0, 0, 0)
        self._similar_vbox.setSpacing(2)
        self._content_layout.addWidget(self._similar_container)

        self._content_layout.addStretch()

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def _load_channel(self, channel_id: str) -> None:
        self._current_id = channel_id
        self._update_nav_state()

        # Reset display to loading state
        self._title_lbl.setText("Loading…")
        self._meta_lbl.clear()
        self._source_lbl.clear()
        self._genres_lbl.clear()
        self._plot_lbl.clear()
        self._cast_lbl.clear()
        self._cast_lbl.hide()
        self._poster_lbl.setPixmap(QPixmap())
        self._poster_lbl.setText("…")
        self._similar_header_lbl.hide()
        self._clear_similar_list()
        self._fav_btn.setText(f"{self._config.unfavorite_icon} Favorite")
        self._like_btn.setChecked(False)
        self._not_interested_btn.setChecked(False)
        self._dislike_btn.setChecked(False)

        self._executor.submit(self._bg_load, channel_id)

    def _bg_load(self, channel_id: str) -> None:
        """Background: fetch channel + metadata from DB, emit _data_ready signal."""
        from metatv.core.database import ChannelDB, MetadataDB, ProviderDB, WatchQueueDB
        from metatv.core.content_dedup import normalize_title, build_dedup_key

        session = self._db.get_session()
        try:
            ch = session.get(ChannelDB, channel_id)
            if not ch:
                self._data_ready.emit(channel_id, {})
                return

            provider = session.get(ProviderDB, ch.provider_id)
            provider_name = provider.name if provider else None

            meta = session.get(MetadataDB, ch.metadata_id) if ch.metadata_id else None

            cast_list: list[str] = []
            if meta and meta.cast:
                try:
                    raw = json.loads(meta.cast) if isinstance(meta.cast, str) else meta.cast
                    cast_list = [
                        (p.get("name") or "") for p in raw[:5] if isinstance(p, dict)
                    ]
                except Exception:
                    pass

            queue_ids = {r.channel_id for r in session.query(WatchQueueDB).all()}

            # Similar titles (same prefix, same media_type, word overlap ≥50%)
            similar: list[dict] = []
            if ch.detected_prefix:
                norm = normalize_title(ch.name, ch.detected_prefix)
                words = [w for w in norm.split() if len(w) >= 4]
                if words:
                    current_key = build_dedup_key(ch, meta)
                    candidates = (
                        session.query(ChannelDB)
                        .filter(
                            ChannelDB.detected_prefix == ch.detected_prefix,
                            ChannelDB.media_type == ch.media_type,
                            ChannelDB.id != channel_id,
                            ChannelDB.is_hidden == False,
                            ChannelDB.name.ilike(f"%{words[0]}%"),
                        )
                        .limit(150)
                        .all()
                    )
                    threshold = max(1, len(words) // 2)
                    seen: set[str] = set()
                    for c in candidates:
                        c_norm = normalize_title(c.name, c.detected_prefix)
                        c_words = {w for w in c_norm.split() if len(w) >= 4}
                        overlap = sum(1 for w in words if w in c_words)
                        if overlap >= threshold and c_norm != norm and c_norm not in seen:
                            c_meta = session.get(MetadataDB, c.metadata_id) if c.metadata_id else None
                            if current_key and build_dedup_key(c, c_meta) == current_key:
                                continue
                            seen.add(c_norm)
                            similar.append({"id": c.id, "name": c.name})
                            if len(similar) >= 12:
                                break

            data = {
                "name": ch.name,
                "media_type": ch.media_type or "",
                "provider_name": provider_name,
                "is_favorite": bool(ch.is_favorite),
                "is_hidden": bool(ch.is_hidden),
                "in_queue": channel_id in queue_ids,
                "user_rating": getattr(ch, "user_rating", 0) or 0,
                "is_suppressed": bool(getattr(ch, "is_suppressed", False)),
                "poster_url": meta.poster_url if meta else None,
                "year": meta.year if meta else None,
                "rating": meta.rating if meta else None,
                "genre": meta.genre if meta else None,
                "plot": meta.plot if meta else None,
                "cast": ", ".join(c for c in cast_list if c),
                "similar": similar,
            }
        except Exception:
            logger.exception("Lightbox bg_load failed for %s", channel_id)
            data = {}
        finally:
            session.close()

        # Signal is thread-safe — Qt queues delivery to the main thread
        self._data_ready.emit(channel_id, data)

    def _apply_data(self, channel_id: str, data: object) -> None:
        """Called on the main thread via _data_ready signal."""
        if channel_id != self._current_id or not self.isVisible():
            return
        if not isinstance(data, dict) or not data:
            self._title_lbl.setText("Could not load details")
            return

        self._title_lbl.setText(data.get("name", "Unknown"))

        meta_parts = []
        if data.get("year"):   meta_parts.append(str(data["year"]))
        if data.get("rating"): meta_parts.append(f"⭐ {data['rating']}")
        self._meta_lbl.setText("  ·  ".join(meta_parts))

        if data.get("provider_name"):
            self._source_lbl.setText(f"Source: {data['provider_name']}")
            self._source_lbl.show()
        else:
            self._source_lbl.hide()

        self._genres_lbl.setText(data.get("genre") or "")
        self._plot_lbl.setText(data.get("plot") or "")

        cast = data.get("cast") or ""
        if cast:
            self._cast_lbl.setText(f"Cast: {cast}")
            self._cast_lbl.show()
        else:
            self._cast_lbl.hide()

        is_fav = data.get("is_favorite", False)
        self._fav_btn.setText(
            f"{self._config.favorite_icon} Unfavorite" if is_fav
            else f"{self._config.unfavorite_icon} Favorite"
        )

        rating = data.get("user_rating", 0) or 0
        self._like_btn.setChecked(rating > 0)
        self._dislike_btn.setChecked(rating < 0)
        self._not_interested_btn.setChecked(bool(data.get("is_suppressed", False)))

        # Similar titles mini-list
        self._clear_similar_list()
        similar = data.get("similar") or []
        if similar:
            self._similar_header_lbl.show()
            for item in similar:
                btn = QPushButton(item["name"])
                btn.setFlat(True)
                btn.setStyleSheet(
                    "QPushButton { text-align: left; color: #aaa; font-size: 11px;"
                    " border: none; padding: 1px 0; }"
                    "QPushButton:hover { color: #fff; }"
                )
                btn.setToolTip(f"Preview: {item['name']}")
                cid = item["id"]
                btn.clicked.connect(lambda _, c=cid: self._dive_into(c))
                self._similar_vbox.addWidget(btn)

        # Poster — check sync cache first, fall back to async
        poster_url = data.get("poster_url")
        if poster_url:
            self._pending_poster_url = poster_url
            pix = self._image_cache.get_image_sync(poster_url)
            if pix:
                self._set_poster(pix)
            else:
                self._image_cache.get_image_async(poster_url)
        else:
            self._poster_lbl.setPixmap(QPixmap())
            self._poster_lbl.setText("No poster")

    def _on_image_loaded(self, url: str, pix: QPixmap) -> None:
        if url == getattr(self, "_pending_poster_url", None) and self.isVisible():
            self._set_poster(pix)

    def _set_poster(self, pix: QPixmap) -> None:
        scaled = pix.scaled(
            QSize(110, 160),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._poster_lbl.setPixmap(scaled)
        self._poster_lbl.setText("")

    def _clear_similar_list(self) -> None:
        while self._similar_vbox.count():
            item = self._similar_vbox.takeAt(0)
            if w := item.widget():
                w.deleteLater()

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
        """Navigate deeper into similar content (rabbit-hole mode)."""
        self._nav_stack.append(self._current_id)
        self._back_btn.show()
        self._load_channel(channel_id)

    def _go_back(self) -> None:
        if not self._nav_stack:
            return
        prev_id = self._nav_stack.pop()
        if not self._nav_stack:
            self._back_btn.hide()
        self._load_channel(prev_id)

    def _update_nav_state(self) -> None:
        in_rabbit_hole = bool(self._nav_stack)
        n = len(self._origin_ids)
        if in_rabbit_hole:
            self._counter_lbl.setText("")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
        else:
            idx = self._origin_idx
            self._counter_lbl.setText(f"{idx + 1} of {n}")
            self._prev_btn.setEnabled(idx > 0)
            self._next_btn.setEnabled(idx < n - 1)

    # ------------------------------------------------------------------ #
    # Dismiss                                                              #
    # ------------------------------------------------------------------ #

    def _close(self) -> None:
        self._nav_stack.clear()
        self._back_btn.hide()
        self.hide()

    def mousePressEvent(self, event) -> None:
        if not self._card.geometry().contains(event.pos()):
            self._close()
        else:
            super().mousePressEvent(event)

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
        painter.fillRect(self.rect(), QColor(0, 0, 0, 170))
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._card.setMaximumHeight(max(400, int(self.height() * 0.85)))
