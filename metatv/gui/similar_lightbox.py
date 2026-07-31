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

import asyncio
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
    from metatv.core.metadata_manager import MetadataManager


class SimilarTitleLightbox(QWidget):
    """Full-window overlay that previews a similar title without replacing the details pane."""

    play_requested        = pyqtSignal(str)       # channel_id
    queue_toggled         = pyqtSignal(str)
    favorite_toggled      = pyqtSignal(str)
    hide_requested        = pyqtSignal(str)
    rating_requested      = pyqtSignal(str, int)  # channel_id, ±1
    suppression_requested = pyqtSignal(str, bool) # channel_id, suppressed
    explore_requested     = pyqtSignal(list)      # seed channel_ids (the walked trail)

    # Internal signal — background thread emits this; main thread receives it
    _data_ready = pyqtSignal(str, object)   # channel_id, data dict

    def __init__(
        self,
        parent: QWidget,
        config: "Config",
        image_cache: "ImageCache",
        db: "Database",
        metadata_manager: "MetadataManager",
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._image_cache = image_cache
        self._db = db
        # The canonical metadata seam — same 3-tier (DB cache → provider raw_data →
        # external API) that the details pane uses; get_metadata also persists on
        # fetch, so repeat opens are cheap. The lightbox must NOT re-read raw
        # MetadataDB rows for the main card (only ~0.2% of channels have a stored
        # row — metadata is fetched on demand), else its card is bare.
        self._metadata_manager = metadata_manager
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
        self._card.explore_clicked.connect(self._on_explore)
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
        """Background: fetch channel + metadata + siblings, emit _data_ready.

        Runs off the UI thread. The MAIN card's rich metadata (poster/plot/cast/
        genres/rating/runtime/year) comes from the canonical
        ``metadata_manager.get_metadata`` seam — the SAME on-demand 3-tier fetch the
        details pane uses (DB cache → provider raw_data → external API; it persists
        on fetch). Reading only the stored ``MetadataDB`` row here left the card bare
        for the ~99.8% of channels never previously opened in details. Never touches
        Qt widgets or the ImageCache (poster pixmaps are built on the main thread in
        ``_apply_data``). Uses ``session_scope`` and returns a plain dict (no ORM /
        ``MetadataResult`` object escapes the block — everything is mapped to
        primitives here).
        """
        from metatv.core.database import ChannelDB, MetadataDB, ProviderDB, UserRatingDB
        from metatv.core.discovery_engine import channel_thumbnail
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.repositories.provider import parse_provider_urls

        # Fetch the main card's metadata via the shared seam FIRST, outside our read
        # session — get_metadata opens (and may write to) its own session, so keeping
        # them non-overlapping avoids any SQLite lock contention.
        meta = self._fetch_main_metadata(channel_id)

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

                # Provider base URLs for poster failover (provider-hosted-poster
                # minority) — mirrors the details pane (main_window_metadata).
                provider_urls: list[str] = []
                if provider and provider.urls:
                    provider_urls = [
                        u.get("url")
                        for u in parse_provider_urls(provider.urls)
                        if u.get("is_active", True) and u.get("url")
                    ]

                # Similar titles — canonical scoped chokepoint (shared with the
                # details-pane row): owns candidate selection, content_key dedup and
                # the visibility gate. PERF GUARD: the strip stays lightweight — name/
                # year from channel fields and the poster resolved ZERO-NETWORK from
                # the channel's own provider data via ``channel_thumbnail`` (the same
                # resolver Discover cards use), falling back to the stored MetadataDB
                # row. We deliberately do NOT call get_metadata for the (up to 12)
                # strip items — 12 on-demand network fetches per open would make
                # browsing janky. Only the MAIN card is enriched on demand.
                # Badge state maps read ONCE (not per item — perf guard preserved): the
                # queued-id set and the like/dislike map, exactly as the details-pane
                # Similar rows are shaped (main_window_metadata._bg_fetch_similar_titles).
                queue_ids = repos.queue.get_queued_ids()
                ratings_map = {
                    r.channel_id: r.rating for r in session.query(UserRatingDB).all()
                }
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
                        "poster_url": channel_thumbnail(c) or (c_meta.poster_url if c_meta else None),
                        "media_type": c.media_type or "",
                        # Strip-card badges (mirror the details-pane Similar rows). All read
                        # from already-loaded columns / the two maps above — no extra query.
                        "user_rating": ratings_map.get(c.id, 0),
                        "in_queue": c.id in queue_ids,
                        "is_favorite": bool(c.is_favorite),
                        "watched": bool(c.watch_completed),
                        "rating": (c_meta.rating if c_meta else None),
                        "lang": (c.detected_region or "").strip(),
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
                            # Source badge for the compact chip (icon glyph + colour).
                            "provider_icon": s.get("provider_icon") or "",
                            "provider_color": s.get("provider_color") or "",
                        })

                data = {
                    "id": channel_id,
                    "name": ch.detected_title or ch.name,
                    "media_type": ch.media_type or "",
                    "provider_name": provider_name,
                    "provider_active": provider_active,
                    "provider_urls": provider_urls,
                    "is_favorite": bool(ch.is_favorite),
                    "is_hidden": bool(ch.is_hidden),
                    "in_queue": repos.queue.is_queued(channel_id),
                    # Real like/dislike from UserRatingDB, real suppression from the
                    # ChannelDB.is_rec_suppressed column (the old getattr(ch,
                    # "user_rating"/"is_suppressed") read columns that don't exist, so
                    # the buttons never lit up).
                    "user_rating": repos.ratings.get(channel_id) or 0,
                    "is_suppressed": bool(ch.is_rec_suppressed),
                    # Main card content: the on-demand MetadataResult (not the stored
                    # row). Falls back to the channel's ingested detected_year.
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

    def _fetch_main_metadata(self, channel_id: str):
        """Fetch the main card's metadata via the shared MetadataManager seam.

        ``get_metadata`` is a coroutine; invoked exactly the way the details pane's
        ``main_window_metadata.fetch_metadata`` does — a private event loop per call,
        run to completion, then closed (we are already off the UI thread here). Never
        raises: on any failure it logs and returns ``None`` so the card degrades to
        the "no rich data" state rather than blanking entirely.

        Returns:
            A ``MetadataResult`` (mapped to primitives by the caller) or ``None``.
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self._metadata_manager.get_metadata(channel_id)
                )
            finally:
                loop.close()
        except Exception:
            logger.exception("Lightbox metadata fetch failed for %s", channel_id)
            return None

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
        # Provider-hosted-poster failover (get_image_async provider_urls) applies
        # ONLY to the main channel's poster — strip posters belong to other
        # channels/providers, so their base URLs don't match.
        provider_urls = data.get("provider_urls") or []
        main_url = self._card.main_poster_url
        for url in self._card.pending_poster_urls():
            pix = self._image_cache.get_image_sync(url)
            if pix:
                self._card.set_poster_pixmap(url, pix)
            else:
                self._image_cache.get_image_async(
                    url, provider_urls=provider_urls if url == main_url else None
                )

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

    def _on_explore(self) -> None:
        """Open the Explore trail-map seeded with the walked dive path.

        The seed is the trail the user actually walked: every prior stop on the
        nav-stack plus the title currently shown.  Emitting the id list lets the
        host build the (data-source-agnostic) trail-map — the same component a later
        Watch-History view seeds with history instead.
        """
        seed = [cid for cid in (self._nav_stack + [self._current_id]) if cid]
        if seed:
            self.explore_requested.emit(seed)

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
        # Responsive, grow-to-content sizing lives in one seam on the card so the
        # width fraction and the 0.9×window height cap are computed in a single
        # place (shared by any offscreen render).
        self._card.apply_overlay_size(self.width(), self.height())
