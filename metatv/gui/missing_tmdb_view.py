"""Missing TMDb data — diagnostic list of idless VOD rows + enrichment analytics.

A read-only diagnostic surface (Phase-2 reshape parts 5 + 6).  It shows:

1. **Enrichment funnel** (analytics) — of the visible VOD corpus, how many rows
   already carry a tmdb id and *how* it was resolved (list harvest / title-sibling
   propagation / provider-detail fetch), and the **residual** that only the
   external TMDb API could resolve.  Decision-support for whether to build the
   Phase-2b TMDb-API layer — never a call to build it.
2. **Idless rows grouped by source** — a drill-down with per-source counts and a
   sample.  Because it is a result surface, opening it feeds the loaded sample ids
   back through the enqueue chokepoint (``MainWindow._enqueue_tmdb_enrichment``),
   so it drives the lazy provider-detail fetch — the list fills in + shrinks as
   ids land (the coalesced toast explains the reflow).

All data loads asynchronously via the ``MainWindow._run_query`` seam and returns
frozen DTOs (no ORM objects cross the boundary).  State is encoded with icons +
text (never colour alone).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import pyqtSignal
from loguru import logger

from metatv.core.repositories.dtos import TmdbFunnelDTO, MissingTmdbSourceDTO
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class MissingTmdbView(QWidget):
    """Diagnostic view: idless VOD rows by source + the enrichment funnel.

    Opening it (``on_activate``) loads the funnel + per-source groups and enqueues
    the loaded sample ids for lazy enrichment.  ``reload`` re-runs the loads (called
    by the host after an enrichment batch collapses rows) so counts settle down.
    """

    done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        # One token per logical query (seam contract) so the two concurrent loads
        # don't drop each other as stale; a deactivate bumps both.
        self._funnel_token = [0]
        self._sources_token = [0]
        self._build_ui()

    # ── UI scaffold ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        back_btn = QPushButton(_icons.prev_icon + " Back")
        back_btn.setToolTip("Return to channel list")
        back_btn.clicked.connect(self.done.emit)
        title = QLabel(f"{_icons.missing_data_icon}  Missing TMDb Data")
        title.setStyleSheet(_theme.DETAIL_TITLE)
        top_bar.addWidget(back_btn)
        top_bar.addWidget(title)
        top_bar.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        self._funnel_panel = QWidget()
        self._funnel_layout = QVBoxLayout(self._funnel_panel)

        self._sources_panel = QWidget()
        self._sources_layout = QVBoxLayout(self._sources_panel)

        content_layout.addWidget(self._section_header("Enrichment Coverage"))
        content_layout.addWidget(self._funnel_panel)
        content_layout.addSpacing(16)
        content_layout.addWidget(self._section_header("Idless Titles by Source"))
        hint = QLabel(
            f"{_icons.info_icon}  Opening this view asks your providers for the "
            "TMDb ids of the sampled titles — the counts shrink as ids arrive."
        )
        hint.setStyleSheet(_theme.SECTION_HINT)
        hint.setWordWrap(True)
        content_layout.addWidget(hint)
        content_layout.addWidget(self._sources_panel)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addLayout(top_bar)
        layout.addWidget(scroll)

    def _section_header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(_theme.SECTION_HDR_LG)
        return label

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Show a loading state, then kick the async loads."""
        for lay in (self._funnel_layout, self._sources_layout):
            self._clear_layout(lay)
            loading = QLabel("Loading…")
            loading.setStyleSheet(_theme.SECTION_HINT)
            lay.addWidget(loading)
        self._load()

    def on_deactivate(self) -> None:
        """Cancel pending loads (bump both query tokens)."""
        self._funnel_token[0] += 1
        self._sources_token[0] += 1

    def reload(self) -> None:
        """Re-run the loads when visible (host calls this after a collapse settle)."""
        if self.isVisible():
            self._load()

    # ── Data loading ────────────────────────────────────────────────────────

    def _load(self) -> None:
        self.main_window._run_query(
            self._query_funnel,
            self._on_funnel_loaded,
            token_ref=self._funnel_token,
            on_error=lambda e: self._on_panel_error(self._funnel_layout, e),
        )
        self.main_window._run_query(
            self._query_sources,
            self._on_sources_loaded,
            token_ref=self._sources_token,
            on_error=lambda e: self._on_panel_error(self._sources_layout, e),
        )

    @staticmethod
    def _query_funnel(repos) -> TmdbFunnelDTO:
        excluded = set(repos.providers.get_hidden_provider_ids())
        return repos.channels.tmdb_enrichment_funnel(excluded)

    @staticmethod
    def _query_sources(repos) -> list[MissingTmdbSourceDTO]:
        excluded = set(repos.providers.get_hidden_provider_ids())
        return repos.channels.missing_tmdb_by_source(excluded)

    # ── Render: funnel / analytics (Part 6) ─────────────────────────────────

    def _on_funnel_loaded(self, dto: TmdbFunnelDTO) -> None:
        self._clear_layout(self._funnel_layout)

        if dto.total_vod == 0:
            self._funnel_layout.addWidget(QLabel("No movie/series content to analyse yet."))
            return

        headline = QLabel(
            f"{_icons.notification_success_icon}  Provider methods identified "
            f"{dto.resolved_pct:.0f}% of {dto.total_vod:,} titles "
            f"({dto.resolved:,} with a TMDb id)."
        )
        headline.setStyleSheet(_theme.SECTION_HDR)
        headline.setWordWrap(True)
        self._funnel_layout.addWidget(headline)

        # Provenance breakdown — icon + label + count (never colour alone).
        for glyph, label, count in (
            (_icons.notification_info_icon or _icons.info_icon, "From provider list", dto.from_list),
            (_icons.recipe_check_icon, "Propagated from a title sibling", dto.propagated),
            (_icons.search_icon, "Fetched from provider detail", dto.fetched),
            (_icons.playback_neutral_icon, "Not yet attempted", dto.unattempted),
        ):
            self._funnel_layout.addWidget(self._stat_row(glyph, label, count, dto.total_vod))

        # The residual — the only-TMDb-API-addressable gap (the decision point).
        residual = QLabel(
            f"{_icons.notification_warning_icon}  {dto.residual:,} titles "
            f"({dto.residual_pct:.0f}%) remain that only the TMDb API could resolve "
            "(provider detail was asked and carried no id)."
        )
        residual.setStyleSheet(_theme.SECTION_HINT)
        residual.setWordWrap(True)
        self._funnel_layout.addSpacing(6)
        self._funnel_layout.addWidget(residual)

    def _stat_row(self, glyph: str, label: str, count: int, total: int) -> QLabel:
        pct = (count / total * 100.0) if total else 0.0
        prefix = f"{glyph}  " if glyph else ""
        row = QLabel(f"{prefix}{label}: {count:,} ({pct:.0f}%)")
        row.setStyleSheet(_theme.SECTION_HINT)
        return row

    # ── Render: idless rows by source (Part 5) ──────────────────────────────

    def _on_sources_loaded(self, groups: list[MissingTmdbSourceDTO]) -> None:
        self._clear_layout(self._sources_layout)

        if not groups:
            done = QLabel(
                f"{_icons.notification_success_icon}  Every visible title has a TMDb id."
            )
            done.setStyleSheet(_theme.SECTION_HINT)
            self._sources_layout.addWidget(done)
            return

        for group in groups:
            self._sources_layout.addWidget(self._source_block(group))

        # Drive enrichment: feed the loaded sample ids through the one chokepoint
        # (same contract as every other result surface — enqueue what we rendered).
        ids = [row.channel_id for g in groups for row in g.sample]
        self.main_window._enqueue_tmdb_enrichment(ids)

    def _source_block(self, group: MissingTmdbSourceDTO) -> QWidget:
        block = QFrame()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 4, 0, 8)

        header = QLabel(
            f"{_icons.provider_icon}  {group.provider_name} — "
            f"{group.missing_count:,} without an id"
            + (f"  ({group.residual_count:,} TMDb-API-only)" if group.residual_count else "")
        )
        header.setStyleSheet(_theme.SECTION_HDR)
        header.setWordWrap(True)
        block_layout.addWidget(header)

        for row in group.sample:
            mtype = _icons.movie_icon if row.media_type == "movie" else _icons.series_icon
            if row.tmdb_addressable:
                flag = f"{_icons.notification_success_icon} likely matchable"
            else:
                flag = f"{_icons.notification_warning_icon} unclear title"
            title = row.detected_title or row.name
            year = f" ({row.detected_year})" if row.detected_year else ""
            line = QLabel(f"    {mtype}  {title}{year}  ·  {flag}")
            line.setStyleSheet(_theme.SECTION_HINT)
            line.setWordWrap(True)
            block_layout.addWidget(line)

        return block

    # ── Error / cleanup ─────────────────────────────────────────────────────

    def _on_panel_error(self, layout, exc: Exception) -> None:
        logger.error("Missing-TMDb panel load failed: {}", exc)
        self._clear_layout(layout)
        err = QLabel(f"{_icons.notification_warning_icon}  Couldn't load this panel")
        err.setStyleSheet(_theme.SECTION_HINT)
        layout.addWidget(err)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
