"""Discovery view — horizontal shelf browse UI (🧭 Discover chip).

Shelves: Recently Added · Top Rated Movies · Top Rated Series ·
         Featured Actor · Genre shelves · Decade shelves.

Data comes entirely from raw_data (no TMDb API key needed). Poster images
use the TMDb CDN URLs already embedded in stream_icon / cover fields and
load on-demand through the existing ImageCache.

Zone model
----------
  Pinned zone    — always expanded, always at top; immune to "Collapse all"
  Expanded zone  — currently browsing; preference-ranked
  ── More Categories ──  (divider, visible when collapsed zone has items)
  Collapsed zone — header-only strips; expands on click

Hidden shelves are not added to the layout at all; only restorable via
the Manage dialog.

Lazy-load design
----------------
Cold-start only fetches cards for pinned/expanded shelves (~4–6 queries).
Collapsed shelves are emitted as header-only strips (no card query at all).
When the user expands a collapsed strip, ``_on_expand_requested`` kicks a
``_ShelfCardsWorker`` that fetches the 30 cards for that shelf, then
``_Shelf.set_cards()`` populates the scroll row.  A ``_loaded_shelf_keys``
set prevents double-fetch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_browse import _BrowseView
from metatv.gui.discover_shelf import _Shelf
from metatv.gui.discover_workers import (
    _LoaderWorker, _SeeAllWorker, _ShelfCardsWorker, _ShelfData,
    _ZoneSnapshot, determine_zone,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache


_DEFAULT_EXPANDED = {"recently_added", "top_movies"}

_ZONE_PINNED    = "pinned"
_ZONE_EXPANDED  = "expanded"
_ZONE_COLLAPSED = "collapsed"


class DiscoverView(QWidget):
    """🧭 Discover — horizontal shelf browse view with two-zone layout."""

    playRequested               = pyqtSignal(str)
    channelSelected             = pyqtSignal(str)
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db: Database, config: Config,
                 image_cache: "ImageCache", parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._image_cache = image_cache
        self._thread: QThread | None = None
        self._see_all_thread: QThread | None = None
        self._see_all_worker: "_SeeAllWorker | None" = None
        # Lazy-expand state
        self._expand_thread: QThread | None = None
        self._expand_worker: "_ShelfCardsWorker | None" = None
        self._inflight_expand: str | None = None  # shelf_key being fetched right now
        self._loaded = False
        self._shelf_data_cache: dict[str, list[ContentCard]] = {}
        self._loaded_shelf_keys: set[str] = set()  # keys whose cards are fetched
        self._shelf_widgets: dict[str, _Shelf] = {}
        self._shelf_zones: dict[str, str] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header bar (manage button)
        header_bar = QWidget()
        header_bar.setFixedHeight(36)
        hbl = QHBoxLayout(header_bar)
        hbl.setContentsMargins(8, 4, 8, 4)
        hbl.addStretch()
        manage_btn = QPushButton(f"{_icons.manage_icon} Manage")
        manage_btn.setFlat(True)
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED}; border: none; font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}"
        )
        manage_btn.clicked.connect(self._open_manage_dialog)
        hbl.addWidget(manage_btn)
        vl.addWidget(header_bar)

        # Stacked: 0 = shelves page, 1 = browse page
        self._stack = QStackedWidget()

        # --- Shelves page ---
        shelves_outer = QScrollArea()
        shelves_outer.setWidgetResizable(True)
        shelves_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shelves_outer.setFrameShape(QScrollArea.Shape.NoFrame)

        self._shelves_inner = QWidget()
        self._shelves_layout = QVBoxLayout(self._shelves_inner)
        self._shelves_layout.setContentsMargins(0, 4, 0, 16)
        self._shelves_layout.setSpacing(8)

        self._loading_lbl = QLabel("Loading…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_XL}; padding: 20px;")
        self._shelves_layout.addWidget(self._loading_lbl)

        # Zone containers
        self._pinned_zone = QWidget()
        self._pinned_layout = QVBoxLayout(self._pinned_zone)
        self._pinned_layout.setContentsMargins(0, 0, 0, 0)
        self._pinned_layout.setSpacing(8)
        self._pinned_zone.setVisible(False)
        self._shelves_layout.addWidget(self._pinned_zone)

        self._expanded_zone = QWidget()
        self._expanded_layout = QVBoxLayout(self._expanded_zone)
        self._expanded_layout.setContentsMargins(0, 0, 0, 0)
        self._expanded_layout.setSpacing(8)
        self._expanded_zone.setVisible(False)
        self._shelves_layout.addWidget(self._expanded_zone)

        self._more_btn = QPushButton("▶  More Categories")
        self._more_btn.setFixedHeight(36)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(
            "QPushButton {"
            f"  background: {_theme.OVERLAY_08};"
            "  border: none;"
            "  border-radius: 4px;"
            f"  color: {_theme.COLOR_MUTED};"
            f"  font-size: {_theme.FONT_LG};"
            "  text-align: left;"
            "  padding: 0 12px;"
            "}"
            "QPushButton:hover {"
            f"  background: {_theme.OVERLAY_15};"
            f"  color: {_theme.COLOR_TEXT};"
            "}"
        )
        self._more_btn.clicked.connect(self._toggle_more_categories)
        self._more_btn.setVisible(False)
        self._more_expanded = self._config.discover_more_expanded
        self._shelves_layout.addWidget(self._more_btn)

        self._collapsed_zone = QWidget()
        self._collapsed_layout = QVBoxLayout(self._collapsed_zone)
        self._collapsed_layout.setContentsMargins(4, 0, 0, 0)
        self._collapsed_layout.setSpacing(2)
        self._collapsed_zone.setVisible(False)
        self._shelves_layout.addWidget(self._collapsed_zone)

        self._shelves_layout.addStretch()

        shelves_outer.setWidget(self._shelves_inner)
        self._stack.addWidget(shelves_outer)

        # --- Browse page ---
        self._browse_view = _BrowseView(self._image_cache, self._config)
        self._browse_view.backRequested.connect(self._on_browse_back)
        self._browse_view.cardClicked.connect(self.channelSelected)
        self._browse_view.cardDoubleClicked.connect(self.playRequested)
        self._browse_view.cardContextMenu.connect(self.channelContextMenuRequested)
        self._stack.addWidget(self._browse_view)

        vl.addWidget(self._stack)

    # ---- Zone helpers -------------------------------------------------------

    def _is_first_launch(self) -> bool:
        cfg = self._config
        return (not cfg.discover_pinned_shelves
                and not cfg.discover_expanded_shelves
                and not cfg.discover_collapsed_shelves
                and not cfg.discover_hidden_shelves)

    def _build_zone_snapshot(self) -> _ZoneSnapshot:
        """Build a thread-safe zone snapshot from the current config."""
        cfg = self._config
        return _ZoneSnapshot(
            pinned=frozenset(cfg.discover_pinned_shelves),
            expanded=frozenset(cfg.discover_expanded_shelves),
            collapsed=frozenset(cfg.discover_collapsed_shelves),
            hidden=frozenset(cfg.discover_hidden_shelves),
            default_expanded=frozenset(_DEFAULT_EXPANDED),
            first_launch=self._is_first_launch(),
        )

    def _determine_zone(self, shelf_key: str) -> str:
        """Route a shelf_key to its zone — delegates to the shared helper."""
        cfg = self._config
        return determine_zone(
            shelf_key,
            pinned=frozenset(cfg.discover_pinned_shelves),
            expanded=frozenset(cfg.discover_expanded_shelves),
            collapsed=frozenset(cfg.discover_collapsed_shelves),
            hidden=frozenset(cfg.discover_hidden_shelves),
            default_expanded=_DEFAULT_EXPANDED,
            first_launch=self._is_first_launch(),
        )

    def _zone_layout(self, zone: str):
        return {
            _ZONE_PINNED:    self._pinned_layout,
            _ZONE_EXPANDED:  self._expanded_layout,
            _ZONE_COLLAPSED: self._collapsed_layout,
        }[zone]

    def _add_to_zone(self, shelf: _Shelf, zone: str) -> None:
        self._zone_layout(zone).addWidget(shelf)
        if zone == _ZONE_PINNED:
            self._pinned_zone.setVisible(True)
        elif zone == _ZONE_EXPANDED:
            self._expanded_zone.setVisible(True)
        elif zone == _ZONE_COLLAPSED:
            self._update_more_btn()

    def _remove_from_zone(self, shelf: _Shelf, zone: str) -> None:
        self._zone_layout(zone).removeWidget(shelf)
        if zone == _ZONE_PINNED and self._pinned_layout.count() == 0:
            self._pinned_zone.setVisible(False)
        elif zone == _ZONE_EXPANDED and self._expanded_layout.count() == 0:
            self._expanded_zone.setVisible(False)
        elif zone == _ZONE_COLLAPSED and self._collapsed_layout.count() == 0:
            self._collapsed_zone.setVisible(False)
            self._update_more_btn()

    def _update_more_btn(self) -> None:
        """Sync the More Categories button label and visibility."""
        count = self._collapsed_layout.count()
        visible = count > 0
        self._more_btn.setVisible(visible)
        if not visible:
            self._collapsed_zone.setVisible(False)
            return
        arrow = _icons.collapse_icon if self._more_expanded else _icons.expand_icon
        self._more_btn.setText(f"{arrow}  More Categories  ({count})")
        self._collapsed_zone.setVisible(self._more_expanded)

    def _toggle_more_categories(self) -> None:
        self._more_expanded = not self._more_expanded
        self._config.discover_more_expanded = self._more_expanded
        self._config.save()
        self._update_more_btn()

    def _move_shelf(self, shelf_key: str, new_zone: str) -> None:
        shelf = self._shelf_widgets.get(shelf_key)
        if shelf is None:
            return
        old_zone = self._shelf_zones.get(shelf_key)
        if old_zone == new_zone:
            return
        if old_zone:
            self._remove_from_zone(shelf, old_zone)
        self._shelf_zones[shelf_key] = new_zone
        shelf.set_collapsed(new_zone == _ZONE_COLLAPSED)
        shelf.set_pinned(new_zone == _ZONE_PINNED)
        self._add_to_zone(shelf, new_zone)

    def _save_zone_config(self) -> None:
        cfg = self._config
        cfg.discover_pinned_shelves    = [k for k, z in self._shelf_zones.items() if z == _ZONE_PINNED]
        cfg.discover_expanded_shelves  = [k for k, z in self._shelf_zones.items() if z == _ZONE_EXPANDED]
        cfg.discover_collapsed_shelves = [k for k, z in self._shelf_zones.items() if z == _ZONE_COLLAPSED]
        cfg.save()

    # ---- Shelf signal handlers ----------------------------------------------

    def _on_pin_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_PINNED)
        self._save_zone_config()

    def _on_unpin_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_EXPANDED)
        self._save_zone_config()

    def _on_collapse_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_COLLAPSED)
        self._save_zone_config()

    def _on_expand_requested(self, shelf_key: str) -> None:
        """Expand a shelf — fetching its cards first if not yet loaded."""
        # Always move the widget to the expanded zone immediately so the UI
        # responds instantly.  The card row will fill in asynchronously if
        # the shelf was header-only.
        self._move_shelf(shelf_key, _ZONE_EXPANDED)
        self._save_zone_config()

        if shelf_key in self._loaded_shelf_keys:
            # Cards already present — nothing more to do.
            return

        if self._inflight_expand == shelf_key:
            # Fetch already in flight for this key — don't double-submit.
            return

        # Kick a lazy card fetch for this shelf.
        self._start_expand_fetch(shelf_key)

    def _start_expand_fetch(self, shelf_key: str) -> None:
        """Start a background ``_ShelfCardsWorker`` for *shelf_key*."""
        # Cancel any previous expand fetch (user expanded a second shelf before
        # the first one finished — keep the most recent request).
        self._stop_loader(
            getattr(self, "_expand_worker", None), self._expand_thread
        )
        self._expand_thread = None
        self._expand_worker = None

        self._inflight_expand = shelf_key
        self._expand_thread = QThread()
        self._expand_worker = _ShelfCardsWorker(self._db, self._config, shelf_key, limit=30)
        self._expand_worker.moveToThread(self._expand_thread)
        self._expand_thread.started.connect(self._expand_worker.run)
        self._expand_worker.ready.connect(self._on_expand_cards_ready)
        self._expand_worker.ready.connect(lambda *_: self._expand_thread.quit())
        self._expand_thread.start()

    def _on_expand_cards_ready(self, shelf_key: str, cards: list) -> None:
        """Called on the main thread when the lazy-expand fetch finishes."""
        self._inflight_expand = None

        shelf = self._shelf_widgets.get(shelf_key)
        if shelf is None:
            return  # shelf was hidden/removed while we were fetching

        # Populate the shelf with its newly fetched cards.
        shelf.set_cards(cards, image_cache=self._image_cache, config=self._config)
        self._shelf_data_cache[shelf_key] = cards
        self._loaded_shelf_keys.add(shelf_key)

        # Trigger image loading for the newly visible cards.
        QTimer.singleShot(120, shelf._load_visible)

    def _on_hide_requested(self, shelf_key: str) -> None:
        shelf = self._shelf_widgets.pop(shelf_key, None)
        if shelf is None:
            return
        old_zone = self._shelf_zones.pop(shelf_key, None)
        if old_zone:
            self._remove_from_zone(shelf, old_zone)
        self._loaded_shelf_keys.discard(shelf_key)
        shelf.deleteLater()
        cfg = self._config
        if shelf_key not in cfg.discover_hidden_shelves:
            cfg.discover_hidden_shelves.append(shelf_key)
        for lst in (cfg.discover_pinned_shelves, cfg.discover_expanded_shelves,
                    cfg.discover_collapsed_shelves):
            if shelf_key in lst:
                lst.remove(shelf_key)
        cfg.save()

    # ---- Load lifecycle -----------------------------------------------------

    def on_activate(self) -> None:
        if not self._loaded:
            self.refresh()

    def on_deactivate(self) -> None:
        """Stop ALL background loader threads so none is destroyed mid-run.

        A QThread destroyed while its thread is still running aborts the whole
        process ("QThread: Destroyed while thread is still running" → core dump).
        The shelf loader, the see-all loader, AND the lazy-expand loader must
        all be stopped here — this runs on view-switch (via the host's
        _hide_all_content_views) and on app close (the closeEvent deactivation
        loop).  Cancelling the worker first is what makes quit()/wait() actually
        succeed: the worker loops monopolize the thread event loop, so quit()
        alone never lands.
        """
        self._stop_loader(getattr(self, "_worker", None), getattr(self, "_thread", None))
        self._stop_loader(getattr(self, "_see_all_worker", None), getattr(self, "_see_all_thread", None))
        self._stop_loader(getattr(self, "_expand_worker", None), getattr(self, "_expand_thread", None))
        # Clear inflight marker so a re-expand of the same key isn't blocked.
        if hasattr(self, "_inflight_expand"):
            self._inflight_expand = None

    @staticmethod
    def _stop_loader(worker, thread) -> None:
        """Cooperatively cancel *worker*, then quit+wait its *thread*."""
        if worker is not None:
            worker.cancel()
        if thread is not None and thread.isRunning():
            thread.quit()
            if not thread.wait(5000):
                # Cancel bounds run() to the current shelf query, so this should
                # not happen; log rather than terminate() (which risks SQLite
                # corruption mid-query).
                logger.warning("Discover loader thread did not stop within 5s")

    def reload(self) -> None:
        """Force a full reload — used when global filters change."""
        self._loaded = False
        self.refresh()

    def refresh(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._loaded = False
        self._shelf_data_cache.clear()
        self._loaded_shelf_keys.clear()
        self._shelf_widgets.clear()
        self._shelf_zones.clear()

        for layout in (self._pinned_layout, self._expanded_layout, self._collapsed_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._pinned_zone.setVisible(False)
        self._expanded_zone.setVisible(False)
        self._collapsed_zone.setVisible(False)
        self._update_more_btn()

        self._loading_lbl.setVisible(True)
        self._loading_lbl.setText("Loading…")

        zone_snapshot = self._build_zone_snapshot()

        self._thread = QThread()
        self._worker = _LoaderWorker(self._db, self._config, zone_snapshot=zone_snapshot)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.shelfReady.connect(self._on_shelf_ready)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_shelf_ready(self, data: _ShelfData) -> None:
        if self._loading_lbl.isVisible():
            self._loading_lbl.setVisible(False)

        zone = self._determine_zone(data.shelf_key)

        if data.header_only:
            # Collapsed strip — no cards yet.  Build the shelf collapsed with
            # an empty card list; cards are fetched on first expand.
            shelf = _Shelf(
                data.title, data.shelf_key, [],
                self._image_cache, self._config,
                pinned=False,
                collapsed=True,
            )
        else:
            # Full shelf with cards.
            self._shelf_data_cache[data.shelf_key] = data.cards
            self._loaded_shelf_keys.add(data.shelf_key)
            shelf = _Shelf(
                data.title, data.shelf_key, data.cards,
                self._image_cache, self._config,
                pinned=(zone == _ZONE_PINNED),
                collapsed=(zone == _ZONE_COLLAPSED),
            )

        shelf.seeAllRequested.connect(self._on_see_all)
        shelf.pinRequested.connect(self._on_pin_requested)
        shelf.unpinRequested.connect(self._on_unpin_requested)
        shelf.collapseRequested.connect(self._on_collapse_requested)
        shelf.expandRequested.connect(self._on_expand_requested)
        shelf.hideRequested.connect(self._on_hide_requested)
        shelf.wire(self.channelSelected, self.playRequested,
                   self.channelContextMenuRequested)

        self._shelf_widgets[data.shelf_key] = shelf
        self._shelf_zones[data.shelf_key] = zone
        self._add_to_zone(shelf, zone)

    def _on_load_finished(self) -> None:
        self._loaded = True
        if self._loading_lbl.isVisible():
            self._loading_lbl.setText("No content found")
        self._update_more_btn()
        QTimer.singleShot(300, self._trigger_image_load_all)

    def _trigger_image_load_all(self) -> None:
        """Fire image loading for all pinned/expanded shelves after zones become visible."""
        for shelf_key, zone in self._shelf_zones.items():
            if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                shelf = self._shelf_widgets.get(shelf_key)
                if shelf:
                    shelf._load_visible()

    # ---- Browse drill-down --------------------------------------------------

    def _on_see_all(self, shelf_key: str) -> None:
        if shelf_key.startswith("genre:"):
            title = shelf_key[6:]
        elif shelf_key.startswith("decade:"):
            title = f"{shelf_key[7:]}s"
        elif shelf_key.startswith("actor:"):
            title = f"Featuring {shelf_key[6:]}"
        elif shelf_key == "recently_added":
            title = "Recently Added"
        elif shelf_key == "top_movies":
            title = "Top Rated Movies"
        elif shelf_key == "top_series":
            title = "Top Rated Series"
        else:
            title = shelf_key

        preview_cards = self._shelf_data_cache.get(shelf_key, [])
        self._browse_view.load(title, preview_cards)
        self._stack.setCurrentIndex(1)

        if self._see_all_thread and self._see_all_thread.isRunning():
            self._see_all_thread.quit()
            self._see_all_thread.wait(500)

        self._see_all_thread = QThread()
        self._see_all_worker = _SeeAllWorker(self._db, self._config, shelf_key)
        self._see_all_worker.moveToThread(self._see_all_thread)
        self._see_all_thread.started.connect(self._see_all_worker.run)

        def _on_ready(key: str, cards: list) -> None:
            if self._stack.currentIndex() == 1:
                self._browse_view.load(title, cards)

        self._see_all_worker.ready.connect(_on_ready)
        self._see_all_worker.ready.connect(lambda *_: self._see_all_thread.quit())
        self._see_all_thread.start()

    def _on_browse_back(self) -> None:
        self._stack.setCurrentIndex(0)

    # ---- Manage dialog ------------------------------------------------------

    def _open_manage_dialog(self) -> None:
        from metatv.gui.discover_filter_dialog import DiscoverManageDialog
        dlg = DiscoverManageDialog(
            self._db, self._config,
            self._shelf_widgets, self._shelf_zones,
            parent=self,
        )
        dlg.exec()
        if dlg._changed:
            self.refresh()
