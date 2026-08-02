"""Viewport-only poster-thumbnail hydration for the channel list.

The channel list is virtualized (``ChannelListModel`` pages in 1,000 rows at a
time) and can hold hundreds of thousands of loaded rows. Requesting a poster
download for every loaded row the moment its data lands would be absurd — this
module exists to request a thumbnail ONLY for the row range currently on
screen, exactly the "the whole point" requirement from the owner spec.

``ChannelThumbnailHydrator`` is a small, Qt-widget-free ``QObject`` owned by
``ChannelListView``. The view is responsible for the Qt-geometry part (turning
scroll/resize events into a ``(first_row, last_row)`` range via ``indexAt``) —
kept there because it depends on real viewport pixels and isn't worth unit
testing in isolation. Everything else (deciding what to request, deduping
against the cache, debouncing, and repainting the right row when an image
arrives) lives here as plain, viewport-pixel-free logic so it is testable by
calling ``request_range(first, last)`` directly with a stub view.

Debounce: ``request_range`` restarts a single-shot ~180ms timer rather than
firing immediately, so a fast fling across thousands of rows coalesces into
one hydration pass instead of queuing a request per intermediate frame.

Threading: ``ImageCache.get_image_async`` does the actual download on its own
thread pool and marshals ``QPixmap`` construction back to the main thread
before emitting ``image_loaded`` (see ``image_cache.py``) — this module never
touches a ``QPixmap`` itself, only the URL string and the signal payload
already built by ``ImageCache``. ``get_image_sync`` (cache-hit only, no I/O) is
used to skip rows that are already on disk — nothing to request there; the
delegate's own ``get_image_sync`` call at paint time will just find it.

Connect/disconnect discipline mirrors ``discover_card.py``'s pattern (see its
``request_image``/``_on_image_loaded``/``_on_image_failed``): the hydrator
connects to the SHARED, long-lived ``ImageCache`` signals once at construction
and exposes ``shutdown()`` to disconnect — call it from the owner's cleanup
path (``MainWindow._register_cleanable``) so a torn-down view never leaves a
dangling connection to a cache instance that outlives it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt, QTimer

from metatv.gui.channel_list_model import POSTER_URL_ROLE, ROW_KIND_ROLE, ChannelListModel

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache

# Debounce interval: a scroll/resize triggers a hydration pass this many ms
# after the LAST such event, not on every single one — see module docstring.
_DEBOUNCE_MS = 180


class ChannelThumbnailHydrator(QObject):
    """Requests poster thumbnails for the channel list's visible row range only.

    Owned by ``ChannelListView`` (see ``set_thumbnail_hydrator``). The view
    calls :meth:`request_range` with the currently visible ``(first_row,
    last_row)`` on scroll, resize, and model reset/insert; the hydrator itself
    decides which of those rows actually need a network request (already-cached
    rows are skipped) and repaints a row via ``dataChanged`` once its image
    lands.
    """

    def __init__(
        self,
        model: ChannelListModel,
        image_cache: "ImageCache",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._image_cache = image_cache
        self._enabled = False
        # url -> set of channel ids currently awaiting that url's image_loaded/
        # image_failed signal (a url can legitimately be requested for more
        # than one row — e.g. two variants sharing the same provider poster).
        self._pending: dict[str, set[str]] = {}
        self._pending_range: tuple[int, int] | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._hydrate_pending_range)

        self._image_cache.image_loaded.connect(self._on_image_loaded)
        self._image_cache.image_failed.connect(self._on_image_failed)

    def set_enabled(self, enabled: bool) -> None:
        """Turn hydration on/off (mirrors ``Config.channel_list_thumbnails``).

        When off, :meth:`request_range` is a no-op — nothing is ever queued or
        requested, matching the delegate's own thumbnails-off behaviour.
        """
        self._enabled = bool(enabled)
        if not self._enabled:
            self._debounce.stop()
            self._pending_range = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def request_range(self, first_row: int, last_row: int) -> None:
        """Debounced entry point: the view's current visible row range.

        Coalesces rapid calls (e.g. every pixel of a scroll) into one
        hydration pass ``_DEBOUNCE_MS`` after the range stops changing.
        """
        if not self._enabled:
            return
        self._pending_range = (first_row, last_row)
        self._debounce.start()

    def _hydrate_pending_range(self) -> None:
        """Request an async load for every visible, uncached, posterful row."""
        if not self._enabled or self._pending_range is None:
            return
        first, last = self._pending_range
        row_count = self._model.rowCount()
        for row in range(max(0, first), min(last, row_count - 1) + 1):
            index = self._model.index(row)
            if not index.isValid():
                continue
            if self._model.data(index, ROW_KIND_ROLE) != "channel":
                continue
            url = self._model.data(index, POSTER_URL_ROLE) or ""
            if not url:
                continue
            if self._image_cache.get_image_sync(url) is not None:
                # Already on disk — the delegate's own paint-time lookup will
                # pick it up on the next repaint; nothing to request.
                continue
            channel_id = self._model.data(index, Qt.ItemDataRole.UserRole)
            self._pending.setdefault(url, set()).add(channel_id)
            self._image_cache.get_image_async(url)

    def _on_image_loaded(self, url: str, pixmap) -> None:
        self._repaint_pending_rows(url)

    def _on_image_failed(self, url: str, error: str) -> None:
        """Drop the pending entry — no repaint needed, the placeholder tile
        already renders on any cache-miss (loading-in-progress and failed
        look identical, so there's nothing new to show)."""
        self._pending.pop(url, None)

    def _repaint_pending_rows(self, url: str) -> None:
        """Emit ``dataChanged`` for every row that was awaiting ``url``."""
        channel_ids = self._pending.pop(url, None)
        if not channel_ids:
            return
        for channel_id in channel_ids:
            row = self._model.row_for_channel_id(channel_id)
            if row is None:
                continue
            idx = self._model.index(row)
            self._model.dataChanged.emit(idx, idx, [POSTER_URL_ROLE])

    def shutdown(self) -> None:
        """Disconnect from the shared ``ImageCache`` signals.

        Call from the owner's cleanup path — see module docstring's
        connect/disconnect discipline note.
        """
        try:
            self._image_cache.image_loaded.disconnect(self._on_image_loaded)
        except TypeError:
            pass
        try:
            self._image_cache.image_failed.disconnect(self._on_image_failed)
        except TypeError:
            pass
