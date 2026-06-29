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

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Pre-built brush for fully-watched non-live rows (built once, reused each data() call).
_WATCHED_DIM_BRUSH = QBrush(QColor(_theme.CHANNEL_ROW_WATCHED_FG))

# Custom role: the row's display text as colour-marked HTML.  The playback-state
# separator glyph (▶/✓) is wrapped in a colour <span> so ChannelRowDelegate can
# paint it in the Resume-orange / watched-green token while the rest of the row
# keeps the default (or dimmed) foreground.  DisplayRole stays PLAIN text (used for
# size hints, accessibility, and the model tests).
CHANNEL_HTML_ROLE = Qt.ItemDataRole.UserRole + 5

# Custom roles used only by the opt-in "Group by type" mode (see set_grouped()):
#   ROW_KIND_ROLE     → "header" for a section header row, "channel" for a normal row.
#   SECTION_TYPE_ROLE → on a header row, the media_type the section groups ("movie"/…).
# Both return "channel"/None in the default flat mode, so callers can branch safely.
ROW_KIND_ROLE = Qt.ItemDataRole.UserRole + 6
SECTION_TYPE_ROLE = Qt.ItemDataRole.UserRole + 7

# Fixed display order + labels for the grouped sections.  Any media_type not in
# this tuple (defensive — should not occur) is appended after these, alphabetically,
# so a row is never silently dropped (mirror-not-cage).
SECTION_ORDER: tuple[str, ...] = ("movie", "series", "live")
_SECTION_LABELS: dict[str, str] = {"movie": "Movies", "series": "Series", "live": "Live"}


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
        # Graduated-watch lower bound (int 0–100; default 10% = config default 0.10)
        self._partial_threshold_pct: int = 10

        # Generation guard: incremented on every set_channels(); page results
        # that were requested before the last reset carry an old generation and
        # are silently dropped by append_page().
        self._generation: int = 0

        # Fast lookup: channel_id → list index (rebuilt on set_channels /
        # append_page so update_favorite is O(1) instead of O(n))
        self._id_to_index: dict[str, int] = {}

        # ── Opt-in "Group by type" state (default OFF = flat list) ──────────────
        # When grouping is ON the same flat ``_channels`` store is re-projected into
        # collapsible Movies/Series/Live sections WITHOUT changing how rows are
        # fetched/paged — grouping is purely a display transform layered over the
        # already-loaded DTOs (see set_grouped / _resolve_row).
        self._grouped: bool = False
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
            return len(self._channels)
        return sum(self._section_size(sec) for sec in self._ordered_sections())

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None

        if not self._grouped:
            row = index.row()
            if not (0 <= row < len(self._channels)):
                return None
            return self._channel_data(self._channels[row], role)

        resolved = self._resolve_row(index.row())
        if resolved is None:
            return None
        kind, payload = resolved
        if kind == "header":
            return self._header_data(payload, role)
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
            # Dim fully-watched non-live rows so finished content recedes visually.
            # Live channels never carry watch state, so they are always full-strength.
            if channel.watch_completed and channel.media_type != "live":
                return _WATCHED_DIM_BRUSH
        if role == Qt.ItemDataRole.ToolTipRole:
            if channel.user_rating == 1:
                return f"You rated this {_icons.like_icon}"
            if channel.user_rating == -1:
                return f"You rated this {_icons.dislike_icon}"
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
            if resolved is not None and resolved[0] == "header":
                return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # ── Group-by-type: section helpers ───────────────────────────────────────

    def _header_data(self, section: str, role: int) -> Any:
        """Return ``data()`` for a section-header row (grouped mode only)."""
        if role == ROW_KIND_ROLE:
            return "header"
        if role == SECTION_TYPE_ROLE:
            return section
        if role in (Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE):
            count = len(self._buckets.get(section, ()))
            label = _SECTION_LABELS.get(section, (section or "Other").title())
            arrow = (
                _icons.expand_icon
                if section in self._collapsed_sections
                else _icons.collapse_icon
            )
            text = f"{arrow} {label} ({count:,})"
            if role == Qt.ItemDataRole.DisplayRole:
                return text
            return (
                f'<span style="color:{_theme.COLOR_TEXT_HI};font-weight:bold">'
                f"{_html.escape(text)}</span>"
            )
        return None

    def _ordered_sections(self) -> list[str]:
        """Sections that currently hold ≥1 loaded row, in fixed display order."""
        present = [s for s in SECTION_ORDER if self._buckets.get(s)]
        extras = sorted(
            s for s in self._buckets
            if s not in SECTION_ORDER and self._buckets.get(s)
        )
        return present + extras

    def _final_section_order(self, extra_keys=()) -> list[str]:
        """Display order over current buckets plus any soon-to-be-created sections."""
        keys = set(self._buckets.keys()) | set(extra_keys)
        known = [s for s in SECTION_ORDER if s in keys]
        others = sorted(k for k in keys if k not in SECTION_ORDER)
        return known + others

    def _section_size(self, section: str) -> int:
        """Number of *display rows* a section occupies (0 if empty)."""
        n = len(self._buckets.get(section, ()))
        if n == 0:
            return 0
        return 1 + (0 if section in self._collapsed_sections else n)

    def _section_display_start(self, section: str, order=None) -> int:
        """Display-row index where ``section``'s header sits."""
        order = order if order is not None else self._final_section_order([section])
        total = 0
        for s in order:
            if s == section:
                return total
            total += self._section_size(s)
        return total

    def _resolve_row(self, row: int) -> Optional[tuple[str, Any]]:
        """Map a grouped display row → ``("header", section)`` or ``("channel", idx)``."""
        for section in self._ordered_sections():
            size = self._section_size(section)
            if row < size:
                if row == 0:
                    return ("header", section)
                # Content rows are only reachable when the section is expanded
                # (collapsed → size==1 so only row 0 is in range).
                return ("channel", self._buckets[section][row - 1])
            row -= size
        return None

    def _extend_bucket(self, section: str, indices: list[int]) -> None:
        """Append channel indices to a section bucket, updating the position map."""
        bucket = self._buckets.setdefault(section, [])
        for ci in indices:
            self._bucket_pos[ci] = len(bucket)
            bucket.append(ci)

    def _rebuild_buckets(self) -> None:
        """Rebuild the section buckets + position map from ``_channels`` order."""
        self._buckets = {}
        self._bucket_pos = {}
        for i, ch in enumerate(self._channels):
            self._extend_bucket(ch.media_type or "other", [i])

    def _display_row_for_channel_index(self, ci: int) -> Optional[int]:
        """Grouped display row for a ``_channels`` index, or None if not visible."""
        if not self._grouped:
            return ci
        if not (0 <= ci < len(self._channels)):
            return None
        section = self._channels[ci].media_type or "other"
        if section in self._collapsed_sections:
            return None  # hidden under a collapsed header
        pos = self._bucket_pos.get(ci)
        if pos is None:
            return None
        return self._section_display_start(section) + 1 + pos

    # ── Group-by-type: public mutators ───────────────────────────────────────

    def set_grouped(self, grouped: bool, collapsed_sections=None) -> None:
        """Turn grouping on/off (a full reset — deliberate user toggle).

        Args:
            grouped: True → project the loaded rows into Movies/Series/Live sections.
            collapsed_sections: Optional iterable of media_types to start collapsed
                (restored from config); ignored when None.
        """
        self.beginResetModel()
        self._grouped = bool(grouped)
        if collapsed_sections is not None:
            self._collapsed_sections = set(collapsed_sections)
        if self._grouped:
            self._rebuild_buckets()
        self.endResetModel()

    def set_section_collapsed(self, section: str, collapsed: bool) -> None:
        """Collapse/expand one section, inserting/removing just its content rows."""
        currently = section in self._collapsed_sections
        if not self._grouped or collapsed == currently:
            # Still record intent so a later set_grouped() restores it.
            if collapsed:
                self._collapsed_sections.add(section)
            else:
                self._collapsed_sections.discard(section)
            return
        n = len(self._buckets.get(section, ()))
        start = self._section_display_start(section)
        if collapsed:
            if n > 0:
                self.beginRemoveRows(QModelIndex(), start + 1, start + n)
                self._collapsed_sections.add(section)
                self.endRemoveRows()
            else:
                self._collapsed_sections.add(section)
        else:
            if n > 0:
                self.beginInsertRows(QModelIndex(), start + 1, start + n)
                self._collapsed_sections.discard(section)
                self.endInsertRows()
            else:
                self._collapsed_sections.discard(section)
        # Repaint the header so its arrow glyph flips.
        hdr = self.createIndex(start, 0)
        self.dataChanged.emit(
            hdr, hdr, [Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE]
        )

    @property
    def is_grouped(self) -> bool:
        """Whether group-by-type display is currently ON."""
        return self._grouped

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
        partial_threshold_pct: int = 10,
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
        self._current_offset = next_offset if next_offset is not None else len(dtos)
        self._provider_icon_map = dict(provider_icon_map)
        self._show_provider_icon = show_provider_icon
        self._favorite_icon = favorite_icon
        self._unfavorite_icon = unfavorite_icon
        self._get_media_type_icon = get_media_type_icon
        self._partial_threshold_pct = partial_threshold_pct
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

    def _append_grouped(self, dtos: list[ChannelListDTO]) -> None:
        """Splice a fetched page into the grouped display, section by section.

        Rows arrive in SQL (name) order — interleaving all media types — so each
        type's new rows land at the END of its section's content block.  Sections
        are processed in display order so every insert position is computed against
        the model state AFTER earlier sections in this batch have been inserted.
        """
        start_index = len(self._channels)
        new_by_section: dict[str, list[int]] = {}
        for offset, ch in enumerate(dtos):
            new_by_section.setdefault(ch.media_type or "other", []).append(
                start_index + offset
            )
        # Store the DTOs first (buckets reference these indices).
        self._channels.extend(dtos)
        self._rebuild_index()

        final_order = self._final_section_order(new_by_section.keys())
        for section in final_order:
            indices = new_by_section.get(section)
            if not indices:
                continue
            existed = bool(self._buckets.get(section))
            collapsed = section in self._collapsed_sections
            if not existed:
                # Brand-new section: header + (rows when expanded) as one block.
                pos = self._section_display_start(section, final_order)
                visible = 1 + (0 if collapsed else len(indices))
                self.beginInsertRows(QModelIndex(), pos, pos + visible - 1)
                self._extend_bucket(section, indices)
                self.endInsertRows()
            elif collapsed:
                # Hidden under a collapsed header — only the count label changes.
                self._extend_bucket(section, indices)
                self._emit_header_changed(section, final_order)
            else:
                old_count = len(self._buckets[section])
                pos = self._section_display_start(section, final_order) + 1 + old_count
                self.beginInsertRows(QModelIndex(), pos, pos + len(indices) - 1)
                self._extend_bucket(section, indices)
                self.endInsertRows()
                self._emit_header_changed(section, final_order)

    def _emit_header_changed(self, section: str, order=None) -> None:
        """Repaint a section header (its count/arrow changed)."""
        start = self._section_display_start(section, order)
        hdr = self.createIndex(start, 0)
        self.dataChanged.emit(
            hdr, hdr, [Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE]
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
        """Rebuild the id→row-index lookup dict."""
        self._id_to_index = {ch.id: i for i, ch in enumerate(self._channels)}

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
    ) -> tuple[str, str, str | None, str]:
        """Compose the row as ``(left, indicator_glyph, indicator_colour, right)``.

        Layout:
            ``{left}{indicator}{right}`` where ``left`` ends with the leading
            icons/tags ("{src}{media}{fav} {prefix_group}") and ``right`` begins
            with a space then the title and trailing badges.  The indicator is the
            fixed-position playback-state separator (replaces the old "·").
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
        quality_str = f" · {channel.detected_quality}" if channel.detected_quality else ""
        year_str = f" · {channel.detected_year}" if channel.detected_year else ""
        bare = channel.detected_title or channel.name

        glyph, colour = self._playback_indicator(channel)

        left = f"{src_badge}{media_icon}{fav_icon} {prefix_group}"
        right = f" {bare}{quality_str}{year_str}"
        if channel.category:
            right += f" [{channel.category}]"
        # Trailing rating glyph — only shown when the user has rated this channel.
        if channel.user_rating == 1:
            right += f" {_icons.like_icon}"
        elif channel.user_rating == -1:
            right += f" {_icons.dislike_icon}"
        return left, glyph, colour, right

    def _compose_display_text(self, channel: ChannelListDTO) -> str:
        """Compose the plain-text row (DisplayRole).

        Format:
            ``{src_badge}{media_icon}{fav_icon} {prefix_group}{indicator} {bare}{quality_str}{year_str}[ [{category}]][ {rating_glyph}]``

        The ``{indicator}`` is the 3-state playback separator (·/▶/✓) — always
        present at the same position so the title column never shifts.  Colour is
        applied only in the HTML role (see ``_compose_display_html``); the plain
        text carries the SHAPE, which is what makes the indicator colourblind-safe.
        """
        left, glyph, _colour, right = self._compose_parts(channel)
        return f"{left}{glyph}{right}"

    def _compose_display_html(self, channel: ChannelListDTO) -> str:
        """Compose the colour-marked HTML row (``CHANNEL_HTML_ROLE``).

        Identical text to ``_compose_display_text`` but the playback-state glyph
        is wrapped in a colour ``<span>`` (Resume-orange for in-progress,
        watched-green for completed) so ``ChannelRowDelegate`` can paint it as
        reinforcement.  All non-glyph text is HTML-escaped (titles can contain
        ``&``/``<``/``>``).
        """
        left, glyph, colour, right = self._compose_parts(channel)
        glyph_html = _html.escape(glyph)
        if colour:
            glyph_html = f'<span style="color:{colour}">{glyph_html}</span>'
        return f"{_html.escape(left)}{glyph_html}{_html.escape(right)}"

    # ── Generation accessor (for append_page callers) ─────────────────────────

    @property
    def generation(self) -> int:
        """Current generation counter — capture this when calling fetchMore/page_requested."""
        return self._generation
