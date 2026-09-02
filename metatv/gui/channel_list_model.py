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

import html as _html
from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor
from loguru import logger

from metatv.core.channel_name_utils import quality_display
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import channel_list_filtering as _filtering
from metatv.gui.channel_list_grouping import (
    SECTION_ORDER, ChannelListGroupingMixin,
)
from metatv.gui.channel_list_roles import (
    CATEGORY_ROLE, CHANNEL_HTML_ROLE, COLLECTION_ROLE, FAV_GLYPH_ROLE,
    EVENT_WINDOW_ROLE,
    GENRE_ROLE, GENRES_ROLE, LANGUAGE_ROLE, LEAGUE_ROLE, MATCH_MARKER_ROLE,
    MEDIA_ICON_ROLE, MEDIA_KIND_ROLE, PLAYBACK_GLYPH_COLOR_ROLE,
    PLAYBACK_GLYPH_ROLE, PLOT_ROLE, POSTER_URL_ROLE, PRIMARY_LANGUAGE_ROLE,
    QUALITY_TOKEN_ROLE, RATING_ROLE, ROW_KIND_ROLE, SECONDARY_LANGUAGE_ROLE,
    SECTION_TYPE_ROLE, SPORT_ROLE, SUBTITLE_MARKER_ROLE, TITLE_ROLE,
    VARIANT_COUNT_ROLE, YEAR_ROLE,
)

#: Re-exported so the sixty-five existing `from channel_list_model import
#: <ROLE>` sites keep working. Declared here rather than silenced with a noqa
#: because __all__ is the executable statement of intent — ruff's F401 deletes
#: an import that is neither used nor declared, and "ignore this" is not a
#: statement of anything. New code imports from the defining module.
__all__ = [
    "ChannelListModel", "SECTION_ORDER",
    "CATEGORY_ROLE", "CHANNEL_HTML_ROLE", "COLLECTION_ROLE", "FAV_GLYPH_ROLE",
    "EVENT_WINDOW_ROLE",
    "GENRE_ROLE", "GENRES_ROLE", "LANGUAGE_ROLE", "LEAGUE_ROLE",
    "MATCH_MARKER_ROLE", "MEDIA_ICON_ROLE", "MEDIA_KIND_ROLE",
    "PLAYBACK_GLYPH_COLOR_ROLE", "PLAYBACK_GLYPH_ROLE", "PLOT_ROLE",
    "POSTER_URL_ROLE", "PRIMARY_LANGUAGE_ROLE", "QUALITY_TOKEN_ROLE",
    "RATING_ROLE", "ROW_KIND_ROLE", "SECONDARY_LANGUAGE_ROLE",
    "SECTION_TYPE_ROLE", "SPORT_ROLE", "SUBTITLE_MARKER_ROLE", "TITLE_ROLE",
    "VARIANT_COUNT_ROLE", "YEAR_ROLE",
]
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

def _watched_dim_brush() -> QBrush:
    """Brush for fully-watched non-live rows — built fresh each call so a live
    theme switch is picked up (cheap; called from the main-thread data() path)."""
    return QBrush(QColor(_theme.CHANNEL_ROW_WATCHED_FG))


def _degraded_dim_brush() -> QBrush:
    """Brush for "degraded" reliability_state rows (graduated play-failure
    ledger — grayed-but-clickable; see theme.CHANNEL_ROW_DEGRADED_FG). Built
    fresh each call so a live theme switch is picked up."""
    return QBrush(QColor(_theme.CHANNEL_ROW_DEGRADED_FG))


# Fixed display order + labels for the grouped sections.  Any media_type not in
# this tuple (defensive — should not occur) is appended after these, alphabetically,
# so a row is never silently dropped (mirror-not-cage).
#: The kinds the V3 row knows how to draw. Anything else (``"unknown"``, a
#: provider-invented string) resolves to ``""``, which the row renders as a
#: generic mark and an omitted kind word — mirror-not-cage: an unrecognised
#: kind still gets a row.
MEDIA_KINDS: tuple[str, ...] = ("live", "movie", "series")


def _media_kind(media_type: str | None) -> str:
    """Normalise a stored ``media_type`` to one of :data:`MEDIA_KINDS`, or ""."""
    value = (media_type or "").strip().lower()
    return value if value in MEDIA_KINDS else ""




# ---------------------------------------------------------------------------
# Page size for incremental fetches triggered by canFetchMore / fetchMore
# ---------------------------------------------------------------------------
_PAGE_SIZE = 1_000


class ChannelListModel(ChannelListGroupingMixin, QAbstractListModel):
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
        # Graduated-watch lower bound (int 0–100; default 10% = config default 0.10)
        self._partial_threshold_pct: int = 10
        # Channel ids that are UNVIEWED watch-for matches — rendered with a 🚨 marker
        # + green title (the colourblind-safe pairing).  Passed in from MainWindow on
        # set_channels (read of config.get_unviewed_vod_match_ids); updated in place by
        # update_new_match_ids() when a match is cleared/found so the green flips live.
        self._new_match_ids: set[str] = set()
        # Unrated row's tooltip falls back to the raw name? See ToolTipRole.
        self._raw_name_tooltip: bool = False

        # Generation guard: incremented on every set_channels(); page results
        # that were requested before the last reset carry an old generation and
        # are silently dropped by append_page().
        self._generation: int = 0

        # Fast lookup: channel_id → list index (rebuilt on set_channels /
        # append_page so update_favorite is O(1) instead of O(n))
        self._id_to_index: dict[str, int] = {}

        # ── Section state ───────────────────────────────────────────────────────
        # Grouping re-projects the flat ``_channels`` store into collapsible
        # sections WITHOUT changing how rows are fetched or paged — purely a
        # display transform over the loaded DTOs (see set_grouped / _resolve_row).
        # Two flags, not one: the checkbox is the user's, and a search groups on
        # its own (by match, not media type) without overwriting their choice.
        self._grouped: bool = False
        self._group_by_type: bool = False
        # Sections the user has narrowed to whole-word matches. EMPTY by
        # default: a section shows everything until someone says otherwise.
        self._word_only: set[str] = set()
        # The sub-filter over rows already loaded, and the indices surviving it.
        # One list for BOTH display modes — flat reads it, grouped buckets from
        # it — so a row cannot be filtered out of the list and still counted by
        # a heading. Never persisted: see channel_list_filtering.
        self._result_filter: str = ""
        self._visible: list[int] = []
        # People whose films are folded away under their name, and how many
        # each has — the count the sub-heading shows, which stays true while
        # the run is collapsed because that is the only thing describing it.
        self._collapsed_people: set[str] = set()
        self._person_counts: dict[str, int] = {}
        # media_types whose section is currently collapsed (header only, rows hidden).
        self._collapsed_sections: set[str] = set()
        # section media_type → list of indices into ``_channels`` (in load order).
        self._buckets: dict[str, list[int]] = {}
        # ``_channels`` index → its 0-based position within its section bucket
        # (so a single-row update maps to a display row in O(1) without scanning).
        self._bucket_pos: dict[int, int] = {}

    # ── QAbstractListModel interface ─────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        if not self._grouped:
            return len(self._visible)
        return sum(self._section_size(sec) for sec in self._ordered_sections())

    def loaded_count(self) -> int:
        """Real channel rows — what every "Showing N channels" must read.

        ``rowCount()`` is the DISPLAY count and includes section headers, which
        every search now creates: three results reported as five.

        Counts what SURVIVES the sub-filter, not what was fetched — the number
        beside a filter that says a different thing from the list under it is
        the reason people stop trusting counts.
        """
        return len(self._visible)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None

        if not self._grouped:
            row = index.row()
            if not (0 <= row < len(self._visible)):
                return None
            return self._channel_data(self._channels[self._visible[row]], role)

        resolved = self._resolve_row(index.row())
        if resolved is None:
            return None
        kind, payload = resolved
        if kind == "header":
            return self._header_data(payload, role)
        if kind == "person":
            return self._person_data(payload, role)
        return self._channel_data(self._channels[payload], role)

    def _channel_data(self, channel: ChannelListDTO, role: int) -> Any:
        """Return ``data()`` for a normal channel row (flat or inside a section)."""
        if role == ROW_KIND_ROLE:
            return "channel"
        if role == Qt.ItemDataRole.DisplayRole:
            return self._compose_display_text(channel)
        if role == CHANNEL_HTML_ROLE:
            return self._compose_display_html(channel)
        if role == Qt.ItemDataRole.UserRole:
            return channel.id
        if role == Qt.ItemDataRole.ForegroundRole:
            # Graduated play-failure ledger: a "degraded" stream (3+ consecutive
            # user-initiated play failures) renders grayed-but-clickable — this
            # takes priority over the watched-dim state below since an unreliable
            # stream is the more actionable signal.
            if channel.reliability_state == "degraded":
                return _degraded_dim_brush()
            # Dim fully-watched non-live rows so finished content recedes visually.
            # Live channels never carry watch state, so they are always full-strength.
            if channel.watch_completed and channel.media_type != "live":
                return _watched_dim_brush()
        if role == Qt.ItemDataRole.ToolTipRole:
            if channel.user_rating == 1:
                return f"You rated this {_icons.like_icon}"
            if channel.user_rating == -1:
                return f"You rated this {_icons.dislike_icon}"
            # Opt-in: the PROVIDER'S RAW NAME when the row shows a cleaned
            # title. OFF by default — the main list deliberately shows no
            # tooltip on an unrated row (test_tooltip_role_unrated_channel_
            # returns_none says so), so this is a parameter, not a behaviour
            # change. Sports turns it on: its titles drop the league and
            # quality the raw name carries ("NHL-TEAM| CALGARY FLAMES HD").
            # A rating tooltip outranks it — that states the user's OWN action.
            if (self._raw_name_tooltip and channel.detected_title
                    and channel.detected_title != channel.name):
                return channel.name
        if role == TITLE_ROLE:
            return channel.detected_title or channel.name
        if role == YEAR_ROLE:
            return channel.detected_year or ""
        if role == QUALITY_TOKEN_ROLE:
            return channel.detected_quality or ""
        if role == LANGUAGE_ROLE:
            return channel.detected_region or ""
        if role == RATING_ROLE:
            return channel.user_rating
        if role == CATEGORY_ROLE:
            return channel.category or ""
        if role == MEDIA_ICON_ROLE:
            return (
                self._get_media_type_icon(channel.media_type)
                if self._get_media_type_icon is not None else ""
            )
        if role == FAV_GLYPH_ROLE:
            return self._favorite_icon if channel.is_favorite else self._unfavorite_icon
        if role == PLAYBACK_GLYPH_ROLE:
            glyph, _ = self._playback_indicator(channel)
            return glyph
        if role == PLAYBACK_GLYPH_COLOR_ROLE:
            _, color = self._playback_indicator(channel)
            return color
        if role == MATCH_MARKER_ROLE:
            return f"{_icons.new_match_icon} " if channel.id in self._new_match_ids else ""
        if role == PLOT_ROLE:
            return channel.plot or ""
        if role == POSTER_URL_ROLE:
            return channel.poster_url or ""
        if role == VARIANT_COUNT_ROLE:
            return channel.variant_count
        if role == PRIMARY_LANGUAGE_ROLE:
            return channel.detected_prefix or ""
        if role == SECONDARY_LANGUAGE_ROLE:
            return channel.detected_collection_language or ""
        if role == SUBTITLE_MARKER_ROLE:
            return channel.detected_collection_subdub or ""
        if role == COLLECTION_ROLE:
            return channel.detected_collection or ""
        if role == GENRE_ROLE:
            return channel.detected_genre or ""
        if role == GENRES_ROLE:
            return tuple(channel.detected_genres or ())
        if role == MEDIA_KIND_ROLE:
            return _media_kind(channel.media_type)
        if role == SPORT_ROLE:
            return getattr(channel, "sport_type", None) or ""
        if role == LEAGUE_ROLE:
            return getattr(channel, "league_name", None) or ""
        if role == EVENT_WINDOW_ROLE:
            # A pair, or None when this row is not a dated fixture — which is
            # ~96% of them. Returning None rather than (None, None) means the
            # cell builder's first check is the common case.
            start = getattr(channel, "event_start_time", None)
            if start is None:
                return None
            return (start, getattr(channel, "event_stop_time", None))
        return None

    def flags(self, index: QModelIndex):  # type: ignore[override]
        """Section headers are clickable (to toggle collapse) but not selectable.

        Making the header enabled-but-not-selectable means a click still emits the
        view's ``clicked`` signal (so the host can toggle the section) without
        stealing the current selection / triggering the details pane.
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self._grouped:
            resolved = self._resolve_row(index.row())
            if resolved is not None and resolved[0] in ("header", "person"):
                # Neither is a channel, so neither is selectable — clicking a
                # sub-heading must not move the details pane to nothing.
                return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


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

    def loaded_search_query(self) -> str:
        """The search text the rows currently loaded were fetched for.

        Empty both when nothing is loaded and when the load had no search term
        — indistinguishable on purpose: a caller asking this wants to know
        whether the rows on screen answer the query in the box, and "no rows"
        and "no query" are the same answer to that.
        """
        return (self._query_params.get("search_query") or "").strip()

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
        partial_threshold_pct: int = 10,
        new_match_ids: Optional[set[str]] = None,
        raw_name_tooltip: bool = False,
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
            partial_threshold_pct: Lower bound int (0–100) below which no progress
                glyph is shown.  Corresponds to
                ``int(config.watch_partial_threshold * 100)``.
        """
        self.beginResetModel()
        self._generation += 1
        self._channels = list(dtos)
        self._has_more = has_more
        self._fetching = False
        self._query_params = dict(query_params)
        # A search groups by MATCH regardless of the checkbox, and clearing it
        # restores what the user had. Derived HERE, the one seam every load passes
        # through holding the params — the alternative is a hand-kept list of
        # "places the search state changes", the enumeration that never stays whole.
        self._grouped = self._group_by_type or bool(
            (query_params.get("search_query") or "").strip())
        self._current_offset = next_offset if next_offset is not None else len(dtos)
        self._provider_icon_map = dict(provider_icon_map)
        self._show_provider_icon = show_provider_icon
        self._favorite_icon = favorite_icon
        self._unfavorite_icon = unfavorite_icon
        self._get_media_type_icon = get_media_type_icon
        self._partial_threshold_pct = partial_threshold_pct
        self._raw_name_tooltip = bool(raw_name_tooltip)
        self._new_match_ids = set(new_match_ids or ())
        self._rebuild_index()
        if self._grouped:
            self._rebuild_buckets()
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

        if self._grouped:
            self._append_grouped(dtos)
        else:
            first = len(self._channels)
            last = first + len(dtos) - 1
            self.beginInsertRows(QModelIndex(), first, last)
            self._channels.extend(dtos)
            self._rebuild_index()
            self.endInsertRows()
        self._has_more = has_more
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
        self._emit_row_changed(idx, [Qt.ItemDataRole.DisplayRole])

    def update_rating(self, channel_id: str, user_rating: int) -> None:
        """Update the rating glyph for one channel row in place.

        Called from the main thread after a DB rating write succeeds.  The DTO
        is frozen, so we replace the entry at that index and emit
        ``dataChanged`` for both DisplayRole (trailing glyph) and ToolTipRole
        (rating tooltip) so the view repaints only that row.

        Args:
            channel_id: The channel whose rating changed.
            user_rating: The new rating: 1 (like), -1 (dislike), or 0 (cleared).
        """
        idx = self._id_to_index.get(channel_id)
        if idx is None:
            return
        from dataclasses import replace
        old = self._channels[idx]
        self._channels[idx] = replace(old, user_rating=user_rating)
        self._emit_row_changed(
            idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole]
        )

    def update_watch_completed(
        self,
        channel_id: str,
        watch_completed: bool,
        watch_percent: int = 100,
        watch_progress: int = 0,
    ) -> None:
        """Update the watched indicator for one channel row in place.

        Called from the main thread after a mark-watched DB write succeeds.  The
        DTO is frozen, so we replace the entry and emit ``dataChanged`` so that
        only that row repaints.

        Args:
            channel_id: The channel whose watch state changed.
            watch_completed: New ``watch_completed`` value.
            watch_percent: New ``watch_percent`` value (default 100 when marking watched).
            watch_progress: New ``watch_progress`` value (default 0 when marking watched).
        """
        idx = self._id_to_index.get(channel_id)
        if idx is None:
            return
        from dataclasses import replace
        old = self._channels[idx]
        self._channels[idx] = replace(
            old,
            watch_completed=watch_completed,
            watch_percent=watch_percent,
            watch_progress=watch_progress,
        )
        self._emit_row_changed(
            idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole]
        )

    def remove_channel(self, channel_id: str) -> None:
        """Remove a single channel row from the model.

        Called from the main thread when the "Hide watched" filter is ON and a
        channel is just marked watched — it should disappear immediately without
        a full reload.

        Args:
            channel_id: The channel to remove.
        """
        idx = self._id_to_index.get(channel_id)
        if idx is None:
            return
        if not self._grouped:
            self.beginRemoveRows(QModelIndex(), idx, idx)
            del self._channels[idx]
            self.endRemoveRows()
            self._rebuild_index()
            return

        # Grouped: a section header is visible even when collapsed, and a section
        # that empties out must lose its header too.
        section = self._channels[idx].media_type or "other"
        disp = self._display_row_for_channel_index(idx)
        bucket_after = len(self._buckets.get(section, ())) - 1
        if bucket_after <= 0:
            # Last row of the section → remove the header (and the row if expanded).
            start = self._section_display_start(section)
            last = start + (0 if section in self._collapsed_sections else 1)
            self.beginRemoveRows(QModelIndex(), start, last)
            del self._channels[idx]
            self._rebuild_index()
            self._rebuild_buckets()
            self.endRemoveRows()
        elif disp is not None:
            self.beginRemoveRows(QModelIndex(), disp, disp)
            del self._channels[idx]
            self._rebuild_index()
            self._rebuild_buckets()
            self.endRemoveRows()
            self._emit_header_changed(section)
        else:
            # Hidden under a collapsed header — only the header count changes.
            del self._channels[idx]
            self._rebuild_index()
            self._rebuild_buckets()
            self._emit_header_changed(section)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _emit_row_changed(self, idx: int, roles: list) -> None:
        """Emit ``dataChanged`` for a ``_channels`` index, mapped to its display row.

        In grouped mode a row hidden under a collapsed section has no visible
        display row → nothing to repaint now (the replaced DTO renders correctly
        once the section is expanded).
        """
        disp = self._display_row_for_channel_index(idx)
        if disp is None:
            return
        mi = self.createIndex(disp, 0)
        self.dataChanged.emit(mi, mi, roles)

    def _rebuild_index(self) -> None:
        """Rebuild the id→row-index lookup dict and the sub-filter's survivors."""
        self._id_to_index = {ch.id: i for i, ch in enumerate(self._channels)}
        self._visible = _filtering.visible_indices(
            self._channels, self._result_filter)

    def set_result_filter(self, text: str) -> None:
        """Narrow the rows already loaded to those carrying *text*.

        A full reset: the survivors are scattered through every section and
        every person run, so there is no contiguous block to hand Qt.
        """
        text = text or ""
        if text == self._result_filter:
            return
        self.beginResetModel()
        self._result_filter = text
        self._rebuild_index()
        if self._grouped:
            self._rebuild_buckets()
        self.endResetModel()

    @property
    def result_filter(self) -> str:
        """The active sub-filter text ("" when nothing is being narrowed)."""
        return self._result_filter

    def _playback_indicator(self, channel: ChannelListDTO) -> tuple[str, str | None]:
        """Return the (glyph, colour) for the row's fixed playback-state separator.

        The separator is always present (so the title column never shifts) and
        is one of three mutually-exclusive states.  SHAPE carries the meaning;
        colour is reinforcement only (None = use the default/dimmed foreground):

            - watched           → ✓  + watched-green token
            - in progress       → ▶  + Resume-orange token
            - not started/live  → ·  + None (neutral)

        Live channels never carry watch state, so they always show the neutral dot.
        """
        if channel.media_type == "live":
            return _icons.playback_neutral_icon, None
        glyph = _icons.playback_state_glyph(
            channel.watch_progress, channel.watch_completed
        )
        if channel.watch_completed:
            return glyph, _theme.COLOR_PLAYBACK_WATCHED
        if channel.watch_progress > 0:
            return glyph, _theme.COLOR_PLAYBACK_IN_PROGRESS
        return glyph, None

    def _compose_parts(
        self, channel: ChannelListDTO
    ) -> tuple[str, str, str | None, str, bool]:
        """Compose the row as ``(left, indicator_glyph, indicator_colour, right, new_match)``.

        Layout:
            ``{left}{indicator}{right}`` where ``left`` ends with the leading
            icons/tags ("{src}{media}{fav} {prefix_group}") and ``right`` begins
            with a space then the title and trailing badges.  The indicator is the
            fixed-position playback-state separator (replaces the old "·").

        When the row is an UNVIEWED watch-for match a 🚨 marker (``new_match_icon``)
        is prepended to the title in ``right`` — the colourblind-safe non-colour cue
        that pairs with the green the HTML role applies.  ``new_match`` (the 5th
        element) tells ``_compose_display_html`` to green the title.  Kept DISTINCT
        from the playback ▶/✓ separator (it sits in the title text, not the
        indicator slot) so the two never collide.
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

        prefix_str = f"[{channel.detected_prefix}] " if channel.detected_prefix else ""
        lang_str = f"[{channel.detected_region}] " if channel.detected_region else ""
        prefix_group = prefix_str + lang_str
        quality_str = (
            f" · {quality_display(channel.detected_quality)}"
            if channel.detected_quality else ""
        )
        year_str = f" · {channel.detected_year}" if channel.detected_year else ""
        bare = channel.detected_title or channel.name

        glyph, colour = self._playback_indicator(channel)

        new_match = channel.id in self._new_match_ids
        match_marker = f"{_icons.new_match_icon} " if new_match else ""

        left = f"{src_badge}{media_icon}{fav_icon} {prefix_group}"
        right = f" {match_marker}{bare}{quality_str}{year_str}"
        if channel.category:
            right += f" [{channel.category}]"
        # Trailing rating glyph — only shown when the user has rated this channel.
        if channel.user_rating == 1:
            right += f" {_icons.like_icon}"
        elif channel.user_rating == -1:
            right += f" {_icons.dislike_icon}"
        return left, glyph, colour, right, new_match

    def _compose_display_text(self, channel: ChannelListDTO) -> str:
        """Compose the plain-text row (DisplayRole).

        Format:
            ``{src_badge}{media_icon}{fav_icon} {prefix_group}{indicator} {bare}{quality_str}{year_str}[ [{category}]][ {rating_glyph}]``

        The ``{indicator}`` is the 3-state playback separator (·/▶/✓) — always
        present at the same position so the title column never shifts.  Colour is
        applied only in the HTML role (see ``_compose_display_html``); the plain
        text carries the SHAPE, which is what makes the indicator colourblind-safe.
        """
        left, glyph, _colour, right, _new_match = self._compose_parts(channel)
        return f"{left}{glyph}{right}"

    def _compose_display_html(self, channel: ChannelListDTO) -> str:
        """Compose the colour-marked HTML row (``CHANNEL_HTML_ROLE``).

        Identical text to ``_compose_display_text`` but the playback-state glyph
        is wrapped in a colour ``<span>`` (Resume-orange for in-progress,
        watched-green for completed) so ``ChannelRowDelegate`` can paint it as
        reinforcement.  An unviewed watch-for match additionally greens its title
        (``COLOR_OK``); the 🚨 marker already in ``right`` is the colourblind-safe
        cue.  All non-glyph text is HTML-escaped (titles can contain ``&``/``<``/``>``).
        """
        left, glyph, colour, right, new_match = self._compose_parts(channel)
        glyph_html = _html.escape(glyph)
        if colour:
            glyph_html = f'<span style="color:{colour}">{glyph_html}</span>'
        right_html = _html.escape(right)
        if new_match:
            right_html = f'<span style="color:{_theme.COLOR_OK}">{right_html}</span>'
        return f"{_html.escape(left)}{glyph_html}{right_html}"

    def update_new_match_ids(self, ids: set[str]) -> None:
        """Replace the unviewed-match id set and repaint loaded rows.

        Called on the main thread when a watch-for match is found or cleared so the
        🚨 marker + green title flip live without a full reload.  Repaints every
        loaded row (Qt only redraws the visible viewport, so this is cheap).
        """
        self._new_match_ids = set(ids or ())
        n = self.rowCount()
        if n > 0:
            top = self.index(0)
            bottom = self.index(n - 1)
            self.dataChanged.emit(
                top, bottom,
                [Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE],
            )

    # ── Generation accessor (for append_page callers) ─────────────────────────

    @property
    def generation(self) -> int:
        """Current generation counter — capture this when calling fetchMore/page_requested."""
        return self._generation
