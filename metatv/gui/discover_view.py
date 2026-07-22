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
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QStackedWidget,
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


_DEFAULT_EXPANDED = {
    "recently_added",
    "top_movies",
    "top_series",
}

_ZONE_PINNED    = "pinned"
_ZONE_EXPANDED  = "expanded"
_ZONE_COLLAPSED = "collapsed"


class DiscoverView(QWidget):
    """🧭 Discover — horizontal shelf browse view with two-zone layout."""

    playRequested               = pyqtSignal(str)
    channelSelected             = pyqtSignal(str)
    channelContextMenuRequested = pyqtSignal(str, int, int)
    channelMiddleClicked        = pyqtSignal(str)   # channel_id — configured middle-click play

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
        # D2 — collapsed strip buffering to eliminate per-item stutter
        self._pending_collapsed: list[_ShelfData] = []
        self._batch_timer: QTimer | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header bar — zoom slider (left of stretch) + Manage button (right)
        header_bar = QWidget()
        header_bar.setFixedHeight(36)
        hbl = QHBoxLayout(header_bar)
        hbl.setContentsMargins(8, 4, 8, 4)
        hbl.setSpacing(6)

        # Zoom icon label
        zoom_lbl = QLabel(_icons.zoom_icon)
        zoom_lbl.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
        zoom_lbl.setToolTip("Resize Discover cards")
        hbl.addWidget(zoom_lbl)

        # Zoom slider — integer range [60, 180], value = round(zoom * 100)
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(60, 180)
        self._zoom_slider.setFixedWidth(110)
        self._zoom_slider.setToolTip("Resize Discover cards")
        # Initialise from persisted config; block signals during restore.
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(round(self._config.discover_zoom * 100))
        self._zoom_slider.blockSignals(False)
        # Debounce timer — fire 300 ms after the user stops dragging
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._apply_zoom)
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        hbl.addWidget(self._zoom_slider)

        hbl.addStretch()

        manage_btn = QPushButton(f"{_icons.manage_icon} Manage")
        manage_btn.setFlat(True)
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
        self._browse_view.cardMiddleClicked.connect(self.channelMiddleClicked)
        self._stack.addWidget(self._browse_view)

        vl.addWidget(self._stack)

    # ---- Zone helpers -------------------------------------------------------

    def _is_first_launch(self) -> bool:
        cfg = self._config
        return (not cfg.discover_pinned_shelves
                and not cfg.discover_expanded_shelves
                and not cfg.discover_collapsed_shelves
                and not cfg.discover_hidden_shelves)

    def _sanitize_zone_config(self) -> None:
        """Ensure the four zone lists are mutually exclusive and de-duplicated.

        A key that appears in more than one list (e.g. ``pinned`` AND
        ``collapsed``) causes an inconsistent UI render.  The rule is simple:
        the highest-priority zone wins — pinned > expanded > collapsed > hidden.
        Any duplicate occurrence in a lower-priority list is silently removed.

        This runs at ``refresh()`` time, before the snapshot is snapshotted and
        handed to the worker, so the worker always sees a clean state.
        """
        cfg = self._config

        # De-dup each list against itself first (shouldn't happen, but guard it).
        def _dedup(lst: list) -> list:
            seen: set[str] = set()
            result = []
            for k in lst:
                if k not in seen:
                    seen.add(k)
                    result.append(k)
            return result

        cfg.discover_pinned_shelves    = _dedup(cfg.discover_pinned_shelves)
        cfg.discover_expanded_shelves  = _dedup(cfg.discover_expanded_shelves)
        cfg.discover_collapsed_shelves = _dedup(cfg.discover_collapsed_shelves)
        cfg.discover_hidden_shelves    = _dedup(cfg.discover_hidden_shelves)

        # Higher-priority zone wins; remove from lower-priority zones.
        pinned_set   = set(cfg.discover_pinned_shelves)
        expanded_set = set(cfg.discover_expanded_shelves)
        hidden_set   = set(cfg.discover_hidden_shelves)

        # Pinned wins over all others.
        cfg.discover_expanded_shelves  = [k for k in cfg.discover_expanded_shelves
                                          if k not in pinned_set]
        cfg.discover_collapsed_shelves = [k for k in cfg.discover_collapsed_shelves
                                          if k not in pinned_set]
        cfg.discover_hidden_shelves    = [k for k in cfg.discover_hidden_shelves
                                          if k not in pinned_set]

        # Rebuild expanded_set after removing pinned duplicates.
        expanded_set = set(cfg.discover_expanded_shelves)

        # Expanded wins over collapsed; hidden wins over collapsed.
        cfg.discover_collapsed_shelves = [k for k in cfg.discover_collapsed_shelves
                                          if k not in expanded_set and k not in hidden_set]

    def _build_zone_snapshot(self) -> _ZoneSnapshot:
        """Build a thread-safe zone snapshot from the current config.

        Sanitises the config first to ensure the four zone lists are mutually
        exclusive — a key cannot be in both ``pinned`` and ``collapsed``.
        """
        self._sanitize_zone_config()
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

    def _add_to_zone(self, shelf: _Shelf, zone: str, at_top: bool = False) -> None:
        layout = self._zone_layout(zone)
        if zone == _ZONE_COLLAPSED and at_top:
            layout.insertWidget(0, shelf)
        else:
            layout.addWidget(shelf)
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
        """Sync the More Categories button label and visibility.

        The count includes both built (already in _collapsed_layout) and
        pending (buffered but not yet built — D2 deferral) collapsed strips so
        the label shows the correct total immediately during streaming load.
        """
        built_count = self._collapsed_layout.count()
        pending_count = len(self._pending_collapsed)
        count = built_count + pending_count
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
        """Move a shelf widget to a new zone.

        Invariant: ``pin ⟹ expand``.  A pinned shelf is ALWAYS rendered
        expanded with its cards visible.  ``set_collapsed(False)`` is called
        whenever *new_zone* is ``_ZONE_PINNED`` so the card row is never hidden.

        If *new_zone* is the collapsed zone and ``config.discover_collapse_to_top``
        is set, the shelf is inserted at position 0 (top) so the user can find
        their recently collapsed item immediately (D4).  Initial-load placement
        always uses ``at_top=False`` (only ``_move_shelf`` calls this for a user
        gesture, and ``_add_collapsed_strip`` handles initial load directly).
        """
        shelf = self._shelf_widgets.get(shelf_key)
        if shelf is None:
            return
        old_zone = self._shelf_zones.get(shelf_key)
        if old_zone == new_zone:
            return
        if old_zone:
            self._remove_from_zone(shelf, old_zone)
        self._shelf_zones[shelf_key] = new_zone
        # pin ⟹ expand: pinned shelves are never collapsed.
        is_pinned = (new_zone == _ZONE_PINNED)
        shelf.set_collapsed(new_zone == _ZONE_COLLAPSED)
        if is_pinned:
            # Unconditionally un-collapse — a pinned shelf is always expanded.
            shelf.set_collapsed(False)
        shelf.set_pinned(is_pinned)
        at_top = (new_zone == _ZONE_COLLAPSED and self._config.discover_collapse_to_top)
        self._add_to_zone(shelf, new_zone, at_top=at_top)

    def _save_zone_config(self) -> None:
        """Persist the current widget zone map to config.

        Derives the three lists directly from ``_shelf_zones`` — the single
        source of truth for where each widget lives.  This guarantees the lists
        are mutually exclusive (a key appears in exactly one list) and that the
        serialised state matches what is rendered.
        """
        cfg = self._config
        cfg.discover_pinned_shelves    = [k for k, z in self._shelf_zones.items() if z == _ZONE_PINNED]
        cfg.discover_expanded_shelves  = [k for k, z in self._shelf_zones.items() if z == _ZONE_EXPANDED]
        cfg.discover_collapsed_shelves = [k for k, z in self._shelf_zones.items() if z == _ZONE_COLLAPSED]
        cfg.save()

    # ---- Shelf signal handlers ----------------------------------------------

    def _flush_if_pending(self, shelf_key: str) -> None:
        """If *shelf_key* is in the D2 pending buffer, flush the whole batch now.

        Pending strips have no widget yet, so any interaction that targets a
        pending key (expand, hide, pin via the Manage dialog) would silently
        no-op without this guard.  Flushing early is safe: the batch builder
        is idempotent and the timer will then find nothing to do when it fires.
        """
        if not self._pending_collapsed:
            return
        is_pending = any(d.shelf_key == shelf_key for d in self._pending_collapsed)
        if not is_pending:
            return
        if self._batch_timer is not None:
            self._batch_timer.stop()
        self._flush_pending_collapsed()

    def _on_pin_requested(self, shelf_key: str) -> None:
        """Pin a shelf — moves it to the pinned zone and ensures cards are loaded.

        ``pin ⟹ expand``: a pinned shelf is always rendered with its full card
        row.  If the shelf was collapsed (header-only), we kick a lazy card fetch
        immediately so the body is populated as soon as the data arrives.
        """
        self._flush_if_pending(shelf_key)
        self._move_shelf(shelf_key, _ZONE_PINNED)
        self._save_zone_config()

        # Ensure content is loaded for the newly-pinned shelf.
        if shelf_key not in self._loaded_shelf_keys:
            if self._inflight_expand != shelf_key:
                self._start_expand_fetch(shelf_key)

    def _on_unpin_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_EXPANDED)
        self._save_zone_config()

    def _on_collapse_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_COLLAPSED)
        self._save_zone_config()

    def _on_expand_requested(self, shelf_key: str) -> None:
        """Expand a shelf — fetching its cards first if not yet loaded.

        If the shelf is still in the D2 pending buffer (not yet built into a
        widget), flush the batch immediately so ``_move_shelf`` finds the widget.
        """
        self._flush_if_pending(shelf_key)
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
        # If this shelf is still pending (D2 buffer), remove it from the buffer
        # directly rather than flushing the whole batch just to delete it.
        still_pending = [d for d in self._pending_collapsed if d.shelf_key == shelf_key]
        if still_pending:
            self._pending_collapsed = [
                d for d in self._pending_collapsed if d.shelf_key != shelf_key
            ]
            self._update_more_btn()
            # Persist the hide immediately.
            cfg = self._config
            if shelf_key not in cfg.discover_hidden_shelves:
                cfg.discover_hidden_shelves.append(shelf_key)
            for lst in (cfg.discover_pinned_shelves, cfg.discover_expanded_shelves,
                        cfg.discover_collapsed_shelves):
                if shelf_key in lst:
                    lst.remove(shelf_key)
            cfg.save()
            return

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

    def _normalize_shelf_config(self) -> None:
        """Canonicalize HTML-entity-encoded genre shelf keys in the persisted config.

        Before bug A was fixed, provider genre strings like "Action &amp; Adventure"
        were stored as-is, creating shelf keys like "genre:Action &amp; Adventure".
        After the fix, get_all_genres() returns canonical "Action & Adventure" which
        produces "genre:Action & Adventure" — a different key.  The two variants
        would both appear in the zone lists, causing the same shelf to show twice.

        This method runs once before the first load and sanitizes all four
        discover_*_shelves lists by:
          1. Unescaping HTML entities in any "genre:*" key.
          2. De-duplicating while preserving original order (first occurrence wins
             so the user's pinned/expanded/collapsed/order state is kept).

        The config is saved only if any list changed.
        """
        import html as _html

        def _clean(key: str) -> str:
            if key.startswith("genre:"):
                return "genre:" + _html.unescape(key[6:])
            return key

        def _dedup_ordered(lst: list) -> list:
            seen: set = set()
            out: list = []
            for item in lst:
                if item not in seen:
                    seen.add(item)
                    out.append(item)
            return out

        cfg = self._config
        changed = False
        for attr in ("discover_pinned_shelves", "discover_expanded_shelves",
                     "discover_collapsed_shelves", "discover_hidden_shelves",
                     "discover_shelf_order"):
            raw: list = list(getattr(cfg, attr, []))
            normalized = _dedup_ordered([_clean(k) for k in raw])
            if normalized != raw:
                setattr(cfg, attr, normalized)
                changed = True
        if changed:
            logger.debug("DiscoverView: migrated HTML-entity genre keys in shelf config")
            cfg.save()

    def on_activate(self) -> None:
        if not self._loaded:
            self._normalize_shelf_config()
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
        # Cancel any pending D2 batch timer and clear the buffer.
        if self._batch_timer is not None:
            self._batch_timer.stop()
        self._pending_collapsed.clear()

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

    # ---- Shelf creation helper -----------------------------------------------

    def _create_and_wire_shelf(
        self,
        data: _ShelfData,
        zone: str,
        *,
        collapsed: bool,
    ) -> _Shelf:
        """Create a ``_Shelf`` widget, wire its signals, and register it.

        This is the *single* place a shelf widget is constructed so the wiring
        is never accidentally duplicated between ``_on_shelf_ready`` (eager
        path) and ``_flush_pending_collapsed`` (D2 batch path).

        Callers are responsible for calling ``_add_to_zone`` afterwards.
        """
        if not data.header_only:
            self._shelf_data_cache[data.shelf_key] = data.cards
            self._loaded_shelf_keys.add(data.shelf_key)

        shelf = _Shelf(
            data.title, data.shelf_key, data.cards,
            self._image_cache, self._config,
            pinned=(zone == _ZONE_PINNED),
            collapsed=collapsed,
        )
        shelf.seeAllRequested.connect(self._on_see_all)
        shelf.pinRequested.connect(self._on_pin_requested)
        shelf.unpinRequested.connect(self._on_unpin_requested)
        shelf.collapseRequested.connect(self._on_collapse_requested)
        shelf.expandRequested.connect(self._on_expand_requested)
        shelf.hideRequested.connect(self._on_hide_requested)
        shelf.wire(self.channelSelected, self.playRequested,
                   self.channelContextMenuRequested, self.channelMiddleClicked)

        self._shelf_widgets[data.shelf_key] = shelf
        self._shelf_zones[data.shelf_key] = zone
        return shelf

    def _on_shelf_ready(self, data: _ShelfData) -> None:
        if self._loading_lbl.isVisible():
            self._loading_lbl.setVisible(False)

        zone = self._determine_zone(data.shelf_key)

        if data.header_only:
            # D2 — buffer collapsed strips; build them in one batch after the
            # stream settles so the "counting up" stutter never happens.
            # Restart a debounce timer; when it fires (≈120 ms of silence) the
            # batch builder creates all pending strips in a single relayout pass.
            self._pending_collapsed.append(data)
            self._update_more_btn()  # shows correct count from pending list
            if self._batch_timer is None:
                self._batch_timer = QTimer(self)
                self._batch_timer.setSingleShot(True)
                self._batch_timer.timeout.connect(self._flush_pending_collapsed)
            self._batch_timer.start(120)
            return

        # Full shelf with cards — build and add immediately (these are the few
        # pinned/expanded shelves the user sees first; they must appear right away).
        shelf = self._create_and_wire_shelf(data, zone, collapsed=(zone == _ZONE_COLLAPSED))
        self._add_to_zone(shelf, zone)

    # ---- D2 batch builder ---------------------------------------------------

    def _flush_pending_collapsed(self) -> None:
        """Build all buffered collapsed strips in one batch (D2).

        Called by the debounce timer after the loader stream settles.  Wraps
        the layout in a single ``setUpdatesEnabled(False/True)`` pass so Qt
        does one relayout instead of one per strip.

        D4 note: these strips come from *initial load*, so they always append
        (``at_top=False``) — only an explicit user collapse uses ``at_top``.
        """
        if not self._pending_collapsed:
            return

        pending = self._pending_collapsed[:]
        self._pending_collapsed.clear()

        self._collapsed_zone.setUpdatesEnabled(False)
        try:
            for data in pending:
                zone = self._determine_zone(data.shelf_key)
                shelf = self._create_and_wire_shelf(data, zone, collapsed=True)
                self._add_to_zone(shelf, zone, at_top=False)
        finally:
            self._collapsed_zone.setUpdatesEnabled(True)

        # Single relayout + button update after all strips are built.
        self._update_more_btn()
        if self._more_expanded:
            self._collapsed_zone.setVisible(True)

    def _on_load_finished(self) -> None:
        self._loaded = True
        if self._loading_lbl.isVisible():
            self._loading_lbl.setText("No content found")
        # Ensure any buffered collapsed strips are built even if the debounce
        # timer hasn't fired yet (e.g. very fast load that finishes before 120 ms).
        if self._pending_collapsed:
            if self._batch_timer is not None:
                self._batch_timer.stop()
            self._flush_pending_collapsed()
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

    # ---- Zoom slider --------------------------------------------------------

    def _on_zoom_slider_changed(self, value: int) -> None:
        """Restart the debounce timer on every slider tick — apply after 300 ms of silence."""
        self._zoom_timer.start(300)

    def _apply_zoom(self) -> None:
        """Clamp, persist, and rebuild shelves at the new zoom level.

        Rebuilds existing shelves' card rows from ``_shelf_data_cache`` without
        re-querying the database — a pure size change should not reorder content.
        Shelves whose cards haven't been fetched yet (header-only collapsed strips)
        just get their scroll-area height updated when they're next expanded.
        """
        raw = self._zoom_slider.value() / 100.0
        zoom = max(0.6, min(1.8, raw))
        if abs(zoom - self._config.discover_zoom) < 0.005:
            return  # no meaningful change

        self._config.discover_zoom = zoom
        self._config.save()
        logger.debug(f"Discover zoom changed to {zoom:.2f}")

        # Rebuild each loaded shelf's card row in-place at the new zoom, reusing
        # the shelf's own set_cards(replace=True) — the single card-build path —
        # so the build/wire/size logic is never duplicated here. Header-only /
        # not-yet-fetched strips are skipped; they pick up the zoom on expand.
        for shelf_key, shelf in list(self._shelf_widgets.items()):
            cards = self._shelf_data_cache.get(shelf_key)
            if cards is None:
                continue
            shelf.set_cards(
                cards, image_cache=self._image_cache, config=self._config,
                replace=True,
            )

        # Trigger image loading for visible cards in non-collapsed shelves.
        QTimer.singleShot(120, self._trigger_image_load_all)

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
