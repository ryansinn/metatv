"""Virtualized channel-list model.

Replaces the old ``QListWidget`` with a ``QAbstractListModel`` that holds
``ChannelListDTO`` objects and pages in data incrementally from the database
as the user scrolls (via ``canFetchMore`` / ``fetchMore``).

Design rules (from CLAUDE.md):
- All DB reads happen off the UI thread via the ``_page_requested`` signal which
  the host (MainWindow) wires to ``_run_query``.
- The model is mutated ONLY on the main thread: inside ``set_channels`` and
  ``append_page`` (both called from the main thread after the async result lands).
- ``ChannelListDTO`` objects are the only data type stored here — no ORM objects.
- Display-text composition happens in ``data(DisplayRole)`` using stored DTO
  fields (never ``parse_channel_name``).
- Colors and font sizes come from ``metatv.gui.theme`` tokens.
- Icons come from ``metatv.gui.icons``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from loguru import logger

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Page size for incremental fetches triggered by canFetchMore / fetchMore
# ---------------------------------------------------------------------------
_PAGE_SIZE = 1_000


class ChannelListModel(QAbstractListModel):
    """Virtualized model for the main channel list.

    Lifecycle:
    1.  ``set_channels(dtos, *, ...)`` — called on the main thread after the
        first SQL page lands.  Resets the model and stores paging context.
    2.  The view calls ``canFetchMore()`` → ``fetchMore()`` as the user scrolls
        near the bottom.  ``fetchMore`` emits ``page_requested`` and the host
        (MainWindow) submits a ``_run_query`` call whose result calls
        ``append_page`` on the main thread.
    3.  ``update_favorite(channel_id, is_favorite)`` — called from
        ``toggle_favorite_by_id`` to flip the icon in-place without a full
        reload.

    Thread safety: ``set_channels``, ``append_page``, and ``update_favorite``
    MUST be called on the main thread.  The model never touches the DB itself.
    """

    # Emitted by fetchMore() so the host can submit the next page query.
    # Payload: (query_params dict, offset int, page_size int)
    page_requested: pyqtSignal = pyqtSignal(dict, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Core data store
        self._channels: list[ChannelListDTO] = []

        # Paging state
        self._has_more: bool = False
        self._fetching: bool = False      # True while a page request is in-flight
        self._query_params: dict = {}     # params snapshot for re-use on next page
        self._current_offset: int = 0    # next SQL OFFSET to request

        # Display helpers (set along with channels so data() can compose text)
        self._provider_icon_map: dict[str, str] = {}
        self._show_provider_icon: bool = False
        self._favorite_icon: str = _icons.favorite_icon
        self._unfavorite_icon: str = _icons.unfavorite_icon
        self._get_media_type_icon: Optional[Callable[[str | None], str]] = None

        # Generation guard: incremented on every set_channels(); page results
        # that were requested before the last reset carry an old generation and
        # are silently dropped by append_page().
        self._generation: int = 0

        # Fast lookup: channel_id → list index (rebuilt on set_channels /
        # append_page so update_favorite is O(1) instead of O(n))
        self._id_to_index: dict[str, int] = {}

    # ── QAbstractListModel interface ─────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._channels)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid() or not (0 <= index.row() < len(self._channels)):
            return None

        channel = self._channels[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._compose_display_text(channel)
        if role == Qt.ItemDataRole.UserRole:
            return channel.id
        return None

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # type: ignore[override]
        if parent.isValid():
            return False
        return self._has_more and not self._fetching

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # type: ignore[override]
        if parent.isValid() or not self._has_more or self._fetching:
            return
        self._fetching = True
        logger.debug(
            f"ChannelListModel.fetchMore: offset={self._current_offset} "
            f"page_size={_PAGE_SIZE} gen={self._generation}"
        )
        self.page_requested.emit(
            dict(self._query_params),
            self._current_offset,
            _PAGE_SIZE,
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def set_channels(
        self,
        dtos: list[ChannelListDTO],
        *,
        provider_icon_map: dict[str, str],
        show_provider_icon: bool,
        has_more: bool,
        query_params: dict,
        next_offset: Optional[int] = None,
        favorite_icon: str = _icons.favorite_icon,
        unfavorite_icon: str = _icons.unfavorite_icon,
        get_media_type_icon: Optional[Callable[[str | None], str]] = None,
    ) -> None:
        """Reset the model with a fresh first page of results.

        Must be called on the main thread.  Increments the generation counter
        so any in-flight page request from a previous query is dropped.

        Args:
            dtos: The first page of channel rows as frozen DTOs.
            provider_icon_map: badge glyph keyed by provider_id.
            show_provider_icon: Whether to prepend provider badges.
            has_more: True when the first page was a full ``_PAGE_SIZE`` result
                      (meaning more rows may exist in the DB).
            query_params: The filter/search params dict used to fetch the first
                          page; stored so ``fetchMore`` can re-issue the query
                          with an incremented offset.
            next_offset: The SQL OFFSET the next page should start at — i.e. the
                         number of RAW rows the first SQL page consumed (before
                         Python-side exclusions). Defaults to ``len(dtos)`` only
                         when omitted; the host must pass the raw count so an
                         active exclusion doesn't desync paging.
            favorite_icon: Glyph for favorited channels.
            unfavorite_icon: Glyph for non-favorited channels.
            get_media_type_icon: Callable (media_type → glyph) injected from
                                 MainWindow so the model can produce the same
                                 icons without importing GUI state.
        """
        self.beginResetModel()
        self._generation += 1
        self._channels = list(dtos)
        self._has_more = has_more
        self._fetching = False
        self._query_params = dict(query_params)
        self._current_offset = next_offset if next_offset is not None else len(dtos)
        self._provider_icon_map = dict(provider_icon_map)
        self._show_provider_icon = show_provider_icon
        self._favorite_icon = favorite_icon
        self._unfavorite_icon = unfavorite_icon
        self._get_media_type_icon = get_media_type_icon
        self._rebuild_index()
        self.endResetModel()
        logger.debug(
            f"ChannelListModel.set_channels: {len(dtos)} rows, "
            f"has_more={has_more}, gen={self._generation}"
        )

    def append_page(
        self,
        dtos: list[ChannelListDTO],
        *,
        has_more: bool,
        generation: int,
        raw_count: Optional[int] = None,
    ) -> None:
        """Append one page of rows fetched by fetchMore().

        Must be called on the main thread.  Drops results whose ``generation``
        does not match the current model generation (they were superseded by a
        set_channels() call triggered by a new filter/search).

        Args:
            dtos: Next page of channel rows (already past Python-side exclusions).
            has_more: True when the SQL page was a full ``_PAGE_SIZE`` result.
            generation: The ``_generation`` value captured when the page was
                        requested; used to drop stale results.
            raw_count: Number of RAW SQL rows the page consumed (before
                       exclusions). The OFFSET advances by this, not by
                       ``len(dtos)`` — otherwise exclusions overlap pages.
                       Defaults to ``len(dtos)`` only when omitted.
        """
        if generation != self._generation:
            logger.debug(
                f"ChannelListModel.append_page: dropping stale page "
                f"(gen {generation} != current {self._generation})"
            )
            self._fetching = False
            return

        advance = raw_count if raw_count is not None else len(dtos)
        # Advance the SQL offset even when every fetched row was excluded, so the
        # next fetch moves past them instead of re-requesting the same window.
        self._current_offset += advance

        if not dtos:
            # A page that was entirely excluded: nothing to insert, but keep
            # paging if the SQL page was full (has_more) so we can reach the
            # surviving rows further down.
            self._has_more = has_more
            self._fetching = False
            return

        first = len(self._channels)
        last = first + len(dtos) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._channels.extend(dtos)
        self._has_more = has_more
        self._rebuild_index()
        self.endInsertRows()
        self._fetching = False
        logger.debug(
            f"ChannelListModel.append_page: +{len(dtos)} rows "
            f"(total {len(self._channels)}), offset={self._current_offset}, has_more={has_more}"
        )

    def mark_fetch_failed(self) -> None:
        """Clear the in-flight flag after a failed page fetch so a later scroll retries."""
        self._fetching = False

    def update_favorite(self, channel_id: str, is_favorite: bool) -> None:
        """Flip the favorite icon for one channel row.

        Called from the main thread after a DB toggle succeeds.  The DTO is
        frozen, so we replace the entry and emit ``dataChanged``.

        Args:
            channel_id: The channel whose favorite state changed.
            is_favorite: The new state (True = favorited).
        """
        idx = self._id_to_index.get(channel_id)
        if idx is None:
            return
        old = self._channels[idx]
        from dataclasses import replace
        self._channels[idx] = replace(old, is_favorite=is_favorite)
        model_index = self.createIndex(idx, 0)
        self.dataChanged.emit(model_index, model_index, [Qt.ItemDataRole.DisplayRole])

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _rebuild_index(self) -> None:
        """Rebuild the id→row-index lookup dict."""
        self._id_to_index = {ch.id: i for i, ch in enumerate(self._channels)}

    def _compose_display_text(self, channel: ChannelListDTO) -> str:
        """Compose the visible row text for *channel*.

        Preserves the exact format from the old ``_on_channels_loaded`` loop:
        ``{src_badge}{media_icon}{fav_icon}{watch_badge} {prefix_group}{dot_sep}{bare}{quality_str}{year_str}[ [{category}]]``

        Watch badges (VOD only — never shown for live channels):
        - ``✓`` when ``watch_completed`` is True.
        - No partial-progress badge in the list (the progress bar lives in the details pane).
        """
        media_icon = (
            self._get_media_type_icon(channel.media_type)
            if self._get_media_type_icon is not None
            else ""
        )
        fav_icon = (
            self._favorite_icon if channel.is_favorite else self._unfavorite_icon
        )
        src_badge = ""
        if self._show_provider_icon and channel.provider_id in self._provider_icon_map:
            src_badge = self._provider_icon_map[channel.provider_id] + " "

        # Watch-completion badge: ✓ for completed VOD; empty for live or unwatched.
        watch_badge = ""
        if channel.media_type != "live" and channel.watch_completed:
            watch_badge = _icons.watched_icon

        prefix_str = f"[{channel.detected_prefix}] " if channel.detected_prefix else ""
        lang_str = f"[{channel.detected_region}] " if channel.detected_region else ""
        prefix_group = prefix_str + lang_str
        dot_sep = "· " if prefix_group.strip() else ""
        quality_str = f" · {channel.detected_quality}" if channel.detected_quality else ""
        year_str = f" · {channel.detected_year}" if channel.detected_year else ""
        bare = channel.detected_title or channel.name
        display_text = (
            f"{src_badge}{media_icon}{fav_icon}{watch_badge} "
            f"{prefix_group}{dot_sep}{bare}{quality_str}{year_str}"
        )
        if channel.category:
            display_text += f" [{channel.category}]"
        return display_text

    # ── Generation accessor (for append_page callers) ─────────────────────────

    @property
    def generation(self) -> int:
        """Current generation counter — capture this when calling fetchMore/page_requested."""
        return self._generation
