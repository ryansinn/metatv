"""Source Analytics view — read-only fingerprint, overlap, unique content, and prefix analysis."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QProgressBar, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt
from loguru import logger

from metatv.core.repositories.dtos import (
    SourceFingerprintDTO,
    OverlapMatrixDTO,
    UniqueChannelDTO,
    PrefixStatDTO,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class SourceAnalyticsView(QWidget):
    """Read-only analytics view for source fingerprinting and overlap analysis.

    Displays:
    1. Source fingerprint (counts, histograms, prefix coverage)
    2. Overlap matrix (N×N Jaccard % heatgrid)
    3. Unique titles (drill-down list)
    4. Unrecognized prefixes (token worklist)

    All data loads asynchronously via MainWindow._run_query seam.
    """

    done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.current_provider_id = None
        # One token per logical query type (seam contract): these panels load
        # concurrently and do NOT supersede each other, so a single shared counter
        # would let each _run_query bump it and drop every sibling's result as stale.
        # A provider switch / deactivate bumps all of them together.
        self._providers_token = [0]
        self._fingerprint_token = [0]
        self._overlap_token = [0]
        self._unique_token = [0]
        self._prefixes_token = [0]

        self._build_ui()

    def _build_ui(self):
        """Build the view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top bar: Back button and title
        top_bar = QHBoxLayout()
        back_btn = QPushButton(_icons.prev_icon + " Back")
        back_btn.setToolTip("Return to channel list")
        back_btn.clicked.connect(self.done.emit)
        title = QLabel("Source Analytics")
        title.setStyleSheet(_theme.DETAIL_TITLE)
        top_bar.addWidget(back_btn)
        top_bar.addWidget(title)
        top_bar.addStretch()

        # Scroll area for main content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # Panel containers
        self._fingerprint_panel = QWidget()
        self._fingerprint_layout = QVBoxLayout(self._fingerprint_panel)

        self._overlap_panel = QWidget()
        self._overlap_layout = QVBoxLayout(self._overlap_panel)

        self._unique_panel = QWidget()
        self._unique_layout = QVBoxLayout(self._unique_panel)

        self._prefixes_panel = QWidget()
        self._prefixes_layout = QVBoxLayout(self._prefixes_panel)

        # Add panels to content
        content_layout.addWidget(self._build_section_header("Source Fingerprint"))
        content_layout.addWidget(self._fingerprint_panel)
        content_layout.addSpacing(20)

        content_layout.addWidget(self._build_section_header("Overlap Matrix"))
        content_layout.addWidget(self._overlap_panel)
        content_layout.addSpacing(20)

        content_layout.addWidget(self._build_section_header("Unique Titles"))
        content_layout.addWidget(self._unique_panel)
        content_layout.addSpacing(20)

        content_layout.addWidget(self._build_section_header("Unrecognized Prefixes"))
        content_layout.addWidget(self._prefixes_panel)
        content_layout.addStretch()

        scroll.setWidget(content)

        layout.addLayout(top_bar)
        layout.addWidget(scroll)

    def _build_section_header(self, title: str) -> QLabel:
        """Build a section header label."""
        label = QLabel(title)
        label.setStyleSheet(_theme.SECTION_HDR_LG)
        return label

    def on_activate(self, provider_id: str):
        """Called when view becomes visible (or the analyzed source switches).

        Clears every panel to a Loading state first so switching sources visibly
        refreshes instead of leaving the previous source's data on screen, then
        kicks off the async loads.
        """
        self.current_provider_id = provider_id
        for layout in (self._fingerprint_layout, self._overlap_layout,
                       self._unique_layout, self._prefixes_layout):
            self._clear_layout(layout)
            loading = QLabel("Loading…")
            loading.setStyleSheet(_theme.SECTION_HINT)
            layout.addWidget(loading)
        self._load_analytics(provider_id)

    def on_deactivate(self):
        """Called when view is hidden. Cancel all pending loads."""
        for ref in (self._providers_token, self._fingerprint_token,
                    self._overlap_token, self._unique_token, self._prefixes_token):
            ref[0] += 1  # Increment to cancel stale loads

    def _load_analytics(self, provider_id: str):
        """Load all analytics data asynchronously."""
        # Get list of all provider IDs for overlap matrix
        def get_provider_ids(repos):
            providers = repos.providers.get_all()
            return [p.id for p in providers]

        # Load provider list first to know which providers to compare
        self.main_window._run_query(
            get_provider_ids,
            self._on_provider_ids_loaded,
            token_ref=self._providers_token,
        )

    def _on_provider_ids_loaded(self, provider_ids: list[str]):
        """Callback after loading provider IDs. Now load all analytics."""
        # Load fingerprint
        self.main_window._run_query(
            lambda repos: repos.analytics.source_fingerprint(self.current_provider_id),
            self._on_fingerprint_loaded,
            token_ref=self._fingerprint_token,
            on_error=lambda e: self._on_panel_error(self._fingerprint_layout, e),
        )

        # Load overlap matrix (all providers x current provider)
        self.main_window._run_query(
            lambda repos: repos.analytics.overlap_matrix(provider_ids, "live"),
            self._on_overlap_loaded,
            token_ref=self._overlap_token,
            on_error=lambda e: self._on_panel_error(self._overlap_layout, e),
        )

        # Load unique titles
        self.main_window._run_query(
            lambda repos: repos.analytics.unique_titles(self.current_provider_id, "live", limit=1000),
            self._on_unique_loaded,
            token_ref=self._unique_token,
            on_error=lambda e: self._on_panel_error(self._unique_layout, e),
        )

        # Load unrecognized prefixes
        self.main_window._run_query(
            lambda repos: repos.analytics.unrecognized_prefixes(self.current_provider_id),
            self._on_prefixes_loaded,
            token_ref=self._prefixes_token,
            on_error=lambda e: self._on_panel_error(self._prefixes_layout, e),
        )

    def _on_fingerprint_loaded(self, dto: SourceFingerprintDTO):
        """Render fingerprint panel."""
        # Clear previous
        self._clear_layout(self._fingerprint_layout)

        # Counts row
        counts_row = QHBoxLayout()
        counts_row.addWidget(QLabel(f"Live: {dto.live_visible:,}"))
        counts_row.addWidget(QLabel(f"Movie: {dto.movie_visible:,}"))
        counts_row.addWidget(QLabel(f"Series: {dto.series_visible:,}"))
        counts_row.addStretch()
        self._fingerprint_layout.addLayout(counts_row)

        # Quality histogram
        if dto.quality_histogram:
            quality_label = QLabel("Quality Distribution:")
            quality_label.setStyleSheet(_theme.SECTION_HDR)
            self._fingerprint_layout.addWidget(quality_label)
            quality_row = QHBoxLayout()
            for quality, count in sorted(dto.quality_histogram.items(), key=lambda x: x[1], reverse=True)[:5]:
                quality_row.addWidget(QLabel(f"{quality}: {count}"))
            quality_row.addStretch()
            self._fingerprint_layout.addLayout(quality_row)

        # Region top-3
        if dto.region_histogram:
            region_label = QLabel("Top Regions:")
            region_label.setStyleSheet(_theme.SECTION_HDR)
            self._fingerprint_layout.addWidget(region_label)
            region_row = QHBoxLayout()
            for region, count in sorted(dto.region_histogram.items(), key=lambda x: x[1], reverse=True)[:3]:
                region_row.addWidget(QLabel(f"{region}: {count:,}"))
            region_row.addStretch()
            self._fingerprint_layout.addLayout(region_row)

        # Prefix coverage percentages
        coverage_row = QHBoxLayout()
        coverage_row.addWidget(QLabel(f"Recognized Prefixes: {dto.recognized_pct:.1f}%"))
        coverage_row.addWidget(QLabel(f"Adult: {dto.adult_pct:.1f}%"))
        coverage_row.addWidget(QLabel(f"Untagged: {dto.untagged_pct:.1f}%"))
        coverage_row.addStretch()
        self._fingerprint_layout.addLayout(coverage_row)

    def _on_overlap_loaded(self, dtos: list[OverlapMatrixDTO]):
        """Render overlap matrix panel."""
        # Clear previous
        self._clear_layout(self._overlap_layout)

        if not dtos:
            self._overlap_layout.addWidget(QLabel("No overlap data available"))
            return

        # Filter to pairs involving current provider
        relevant = [d for d in dtos if d.provider_a_id == self.current_provider_id or d.provider_b_id == self.current_provider_id]

        # Headline: show overlap with other providers (by NAME, not UUID)
        headlines = []
        for dto in relevant:
            if dto.provider_a_id == self.current_provider_id and dto.provider_b_id != self.current_provider_id:
                cur_name, other_name = dto.provider_a_name, dto.provider_b_name
            elif dto.provider_b_id == self.current_provider_id and dto.provider_a_id != self.current_provider_id:
                cur_name, other_name = dto.provider_b_name, dto.provider_a_name
            else:
                continue
            pct = dto.jaccard * 100
            headlines.append(f"{cur_name} is {pct:.1f}% shared with {other_name} (estimate)")

        for headline in headlines:
            self._overlap_layout.addWidget(QLabel(headline))

        # Simple table of overlaps (limited to non-identity pairs)
        non_identity = [d for d in relevant if d.provider_a_id != d.provider_b_id]
        if non_identity:
            table = QTableWidget(len(non_identity), 4)
            table.setHorizontalHeaderLabels(["Source A", "Source B", "Shared", "Jaccard %"])
            for row, dto in enumerate(non_identity[:10]):  # Limit to top 10
                table.setItem(row, 0, QTableWidgetItem(dto.provider_a_name))
                table.setItem(row, 1, QTableWidgetItem(dto.provider_b_name))
                table.setItem(row, 2, QTableWidgetItem(str(dto.shared)))
                table.setItem(row, 3, QTableWidgetItem(f"{dto.jaccard * 100:.1f}%"))
            table.resizeColumnsToContents()
            self._overlap_layout.addWidget(table)

    def _on_unique_loaded(self, dtos: list[UniqueChannelDTO]):
        """Render unique titles panel."""
        # Clear previous
        self._clear_layout(self._unique_layout)

        if not dtos:
            self._unique_layout.addWidget(QLabel("No unique titles on this provider"))
            return

        # Summary
        self._unique_layout.addWidget(QLabel(f"Found {len(dtos):,} unique titles"))

        # Table of first 50 unique channels
        table = QTableWidget(min(len(dtos), 50), 5)
        table.setHorizontalHeaderLabels(["Name", "Title", "Region", "Quality", "Year"])
        for row, dto in enumerate(dtos[:50]):
            table.setItem(row, 0, QTableWidgetItem(dto.name[:50]))  # Truncate long names
            table.setItem(row, 1, QTableWidgetItem(dto.detected_title or ""))
            table.setItem(row, 2, QTableWidgetItem(dto.detected_region or ""))
            table.setItem(row, 3, QTableWidgetItem(dto.detected_quality or ""))
            table.setItem(row, 4, QTableWidgetItem(dto.detected_year or ""))
        table.resizeColumnsToContents()
        self._unique_layout.addWidget(table)

    def _on_prefixes_loaded(self, dtos: list[PrefixStatDTO]):
        """Render unrecognized prefixes panel."""
        # Clear previous
        self._clear_layout(self._prefixes_layout)

        if not dtos:
            self._prefixes_layout.addWidget(QLabel("All prefixes recognized"))
            return

        # Table of unrecognized prefixes
        table = QTableWidget(min(len(dtos), 100), 3)
        table.setHorizontalHeaderLabels(["Prefix", "Count", "Examples"])
        for row, dto in enumerate(dtos[:100]):
            table.setItem(row, 0, QTableWidgetItem(dto.prefix))
            table.setItem(row, 1, QTableWidgetItem(str(dto.count)))
            examples = ", ".join(dto.sample_names[:3])
            table.setItem(row, 2, QTableWidgetItem(examples[:60]))
        table.resizeColumnsToContents()
        self._prefixes_layout.addWidget(table)

    def _on_panel_error(self, layout, exc: Exception):
        """Render a visible failure row in a panel whose query raised (main thread).

        Without this, a failed load would leave the panel blank — indistinguishable
        from an empty result (CLAUDE.md: background refresh failure must be visible).
        """
        logger.error("Source analytics panel load failed: {}", exc)
        self._clear_layout(layout)
        err = QLabel(f"{_icons.notification_warning_icon}  Couldn't load this panel")
        err.setStyleSheet(_theme.SECTION_HINT)
        layout.addWidget(err)

    def _clear_layout(self, layout):
        """Clear all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
