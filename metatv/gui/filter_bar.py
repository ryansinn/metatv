"""Filter bar widget for channel filtering"""

from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QMenu, QCheckBox, QScrollArea, QFrame, QWidgetAction, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from loguru import logger

from metatv.gui import theme as _theme


class ToggleChip(QPushButton):
    """Toggle chip button for simple on/off filtering"""

    toggled_changed = pyqtSignal(bool)

    def __init__(self, label: str, enabled: bool = True):
        super().__init__()
        self.label = label
        self._enabled = enabled
        self._count = None
        self.setCheckable(True)
        self.setChecked(enabled)
        self.update_appearance()
        self.clicked.connect(self.on_clicked)

    def on_clicked(self):
        self._enabled = self.isChecked()
        self.update_appearance()
        self.toggled_changed.emit(self._enabled)

    def set_count(self, count: int):
        self._count = count if count > 0 else None
        self.update_appearance()

    def update_appearance(self):
        label_text = self.label
        if self._count is not None:
            label_text = f"{self.label} ({self._count})"

        if self._enabled:
            self.setText(f"{label_text} ●")
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_theme.COLOR_ACCENT_BLUE};
                    color: white;
                    border: none;
                    border-radius: 12px;
                    padding: 6px 14px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #5599ff; }}
            """)
        else:
            self.setText(f"{label_text} ○")
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #e0e0e0;
                    color: {_theme.COLOR_MUTED_2};
                    border: 1px solid {_theme.COLOR_TEXT};
                    border-radius: 12px;
                    padding: 6px 14px;
                }}
                QPushButton:hover {{ background-color: #d0d0d0; }}
            """)

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.blockSignals(True)
        self.setChecked(enabled)
        self.blockSignals(False)
        self.update_appearance()


class FilterChip(ToggleChip):
    """Three-state chip for the global content filter.

    States:
      no-filter  — gray ○, click opens dialog
      active     — teal ●, click pauses, right-click opens dialog
      paused     — amber ●, click resumes, right-click opens dialog

    toggled_changed(bool):
      True  = filter should be active (resume)
      False = filter should be paused
    open_dialog_requested = right-click or click-when-no-filters
    """

    open_dialog_requested = pyqtSignal()

    _ACTIVE_STYLE = _theme.EXCL_CHIP_ACTIVE
    _PAUSED_STYLE = _theme.EXCL_CHIP_PAUSED

    def __init__(self, label: str):
        super().__init__(label, enabled=False)
        # Disable checkable state: ToggleChip sets setCheckable(True), but on Linux/Wayland
        # Qt's native checkable-button renderer splits the hit-test region so the text area
        # registers no clicks. FilterChip manages all visual state via setStyleSheet and
        # never reads isChecked(), so removing checkable has no functional effect.
        self.setCheckable(False)
        self._paused = False
        self._has_filters = False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda _: self.open_dialog_requested.emit()
        )
        self.setToolTip("Content category filters — click to configure")

    def set_filter_state(self, has_filters: bool, paused: bool) -> None:
        self._has_filters = has_filters
        self._paused = paused
        self.blockSignals(True)
        self.set_enabled(has_filters)
        self.blockSignals(False)
        if has_filters and paused:
            self.setText(f"{self.label} ●")
            self.setStyleSheet(self._PAUSED_STYLE)
            self.setToolTip("Filters paused — click to resume · right-click to edit")
        elif has_filters:
            self.setText(f"{self.label} ●")
            self.setStyleSheet(self._ACTIVE_STYLE)
            self.setToolTip("Filters active — click to pause · right-click to edit")
        else:
            self.update_appearance()   # standard gray ○
            self.setToolTip("Content category filters — click to configure")

    def on_clicked(self) -> None:
        if self._has_filters:
            # Toggle pause/resume — keep chip lit, don't flip _enabled
            self.blockSignals(True)
            self.set_enabled(True)
            self.blockSignals(False)
            # True = resume (un-pause), False = pause
            self.toggled_changed.emit(self._paused)
        else:
            # No filters configured — open dialog
            self.open_dialog_requested.emit()


class FilterDropdown(QPushButton):
    """Dropdown button with multi-select checkboxes"""

    filter_changed = pyqtSignal()

    def __init__(self, label: str, groups: Dict[str, int], all_selected: bool = True):
        super().__init__()
        self.label = label
        self.groups = groups
        self.selected_groups: set = set(groups.keys()) if all_selected else set()

        self.setText(f"{label} ▼")
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {_theme.COLOR_LINE};
                border: 1px solid {_theme.COLOR_TEXT};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{ background-color: #f5f5f5; color: {_theme.COLOR_LINE}; }}
        """)

        self.menu = QMenu(self)
        self.checkboxes = {}
        self.setup_menu()
        self.clicked.connect(self.show_menu)

    def setup_menu(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        scroll.setMaximumHeight(400)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        for group_name in sorted(self.groups.keys()):
            count = self.groups[group_name]
            checkbox = QCheckBox(f"{group_name} ({count:,})")
            checkbox.setChecked(group_name in self.selected_groups)
            checkbox.stateChanged.connect(
                lambda state, name=group_name: self.on_checkbox_changed(name, state)
            )
            self.checkboxes[group_name] = checkbox
            layout.addWidget(checkbox)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        button_layout.addWidget(select_all_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_all)
        button_layout.addWidget(clear_btn)
        layout.addLayout(button_layout)

        scroll.setWidget(container)
        widget_action = QWidgetAction(self.menu)
        widget_action.setDefaultWidget(scroll)
        self.menu.addAction(widget_action)

    def show_menu(self):
        self.menu.exec(QCursor.pos())

    def on_checkbox_changed(self, group_name: str, state: int):
        if state == Qt.CheckState.Checked.value:
            self.selected_groups.add(group_name)
        else:
            self.selected_groups.discard(group_name)
        self.update_button_label()
        self.filter_changed.emit()

    def select_all(self):
        self.selected_groups = set(self.groups.keys())
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    def clear_all(self):
        self.selected_groups.clear()
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    def update_button_label(self):
        total = len(self.groups)
        selected = len(self.selected_groups)
        if selected == total:
            self.setText(f"{self.label} ▼")
        elif selected == 0:
            self.setText(f"{self.label} (None) ▼")
        else:
            self.setText(f"{self.label} ({selected}/{total}) ▼")

    def get_selected(self) -> List[str]:
        return list(self.selected_groups)

    def update_groups(self, groups: Dict[str, int]):
        self.groups = groups
        self.menu.clear()
        self.checkboxes.clear()
        self.setup_menu()
        self.update_button_label()


class FilterBar(QWidget):
    """Filter bar with language/quality dropdowns, source chips, and untagged toggle."""

    filter_changed = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._restoring_state = False
        self._source_chips: Dict[str, ToggleChip] = {}  # provider_id → chip

        self.setup_ui()
        self.restore_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Row 0: source chips (multi-provider only — hidden when ≤1 provider)
        self._source_row_widget = QWidget()
        source_row = QHBoxLayout(self._source_row_widget)
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        self._source_chips_label = QLabel("Sources:")
        self._source_chips_label.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: 11px;")
        source_row.addWidget(self._source_chips_label)
        self._source_chips_layout = source_row
        source_row.addStretch()
        self._source_row_widget.hide()
        layout.addWidget(self._source_row_widget)

        # Row 1: filter dropdowns + untagged checkbox
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Only Show:"))

        self.language_dropdown = FilterDropdown("Language", {})
        self.language_dropdown.setToolTip(
            "Filter by audio language.\n"
            "\n"
            "Selecting a language includes audio, dubbed, and subtitled variants for that\n"
            "language — all content directed at that linguistic audience.\n"
            "\n"
            "Broad groups (English, Spanish, French…) match all variants of that language.\n"
            "Locale sub-groups (English (North America), French (Europe)…) match only channels\n"
            "where the provider explicitly labeled them with a country code (US, CA, FR…).\n"
            "Channels with a generic code (EN, ES, FR) appear in the broad group only.\n"
            "\n"
            "Language and Region both ADD to your results when combined — selecting either\n"
            "or both grows the content pool, it never restricts it.\n"
            "\n"
            "Select nothing = no language filter (show all)."
        )
        self.language_dropdown.filter_changed.connect(self.on_filter_changed)
        filter_row.addWidget(self.language_dropdown)

        self.region_dropdown = FilterDropdown("Region", {})
        self.region_dropdown.setToolTip(
            "Filter by geographic origin or audience target.\n"
            "\n"
            "Region filters use the explicit geographic labels the provider assigned —\n"
            "e.g. MX/MEX channels are Mexican content, not just Spanish content.\n"
            "This lets you find exactly your region's channels without browsing all of\n"
            "a language group.\n"
            "\n"
            "Region and Language both ADD to your results when combined — selecting either\n"
            "or both grows the content pool, it never restricts it.\n"
            "\n"
            "Select nothing = no region filter (show all)."
        )
        self.region_dropdown.filter_changed.connect(self.on_filter_changed)
        self.region_dropdown.hide()  # shown only when regional data exists
        filter_row.addWidget(self.region_dropdown)

        self.quality_dropdown = FilterDropdown("Quality", {})
        self.quality_dropdown.setToolTip(
            "Filter by quality tier (RAW, 4K, HD, SD, etc.).\n"
            "Restrictive: only channels explicitly tagged with the selected quality show.\n"
            "Select nothing = show all quality levels."
        )
        self.quality_dropdown.filter_changed.connect(self.on_filter_changed)
        self.quality_dropdown.hide()  # shown only when quality data exists
        filter_row.addWidget(self.quality_dropdown)

        self.platform_dropdown = FilterDropdown("Platform", {})
        self.platform_dropdown.setToolTip(
            "Filter by streaming service or platform (Netflix, EAR, VIX, etc.).\n"
            "Platform selections ADD to your results alongside Language and Region.\n"
            "Select nothing = no platform filter (show all)."
        )
        self.platform_dropdown.filter_changed.connect(self.on_filter_changed)
        self.platform_dropdown.hide()  # shown only when platform data exists
        filter_row.addWidget(self.platform_dropdown)

        filter_row.addSpacing(12)

        self.include_untagged_check = QCheckBox("Show untagged content")
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.setToolTip(
            "Applies to the Category filter only.\n"
            "When checked: content with no category tag shows alongside matching categories.\n"
            "When unchecked: only content explicitly tagged with a selected category shows.\n"
            "Has no effect when no Category filter is active."
        )
        self.include_untagged_check.stateChanged.connect(self.on_filter_changed)
        filter_row.addWidget(self.include_untagged_check)

        filter_row.addSpacing(12)

        # Adult content: hidden by default; shown via set_adult_filter_visible()
        self._adult_filter_widget = QWidget()
        adult_row = QHBoxLayout(self._adult_filter_widget)
        adult_row.setContentsMargins(0, 0, 0, 0)
        adult_row.setSpacing(4)
        adult_row.addWidget(QLabel("Adult:"))
        self.adult_mode_combo = QComboBox()
        self.adult_mode_combo.addItems(["All", "Hide adult", "Adult only"])
        self.adult_mode_combo.setCurrentIndex(1)  # default: Hide adult
        self.adult_mode_combo.setToolTip(
            "All — show all channels including adult-flagged\n"
            "Hide adult — hide channels marked as adult (default)\n"
            "Adult only — show only adult-flagged channels"
        )
        self.adult_mode_combo.currentIndexChanged.connect(self.on_filter_changed)
        adult_row.addWidget(self.adult_mode_combo)
        self._adult_filter_widget.setVisible(False)  # hidden until adult content exists
        filter_row.addWidget(self._adult_filter_widget)

        self.clear_filters_btn = QPushButton("Clear")
        self.clear_filters_btn.setToolTip("Reset all filters — show everything")
        self.clear_filters_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #e0e0e0; color: {_theme.COLOR_LINE};
                border: 1px solid {_theme.COLOR_TEXT}; border-radius: 4px; padding: 6px 12px;
            }}
            QPushButton:hover {{ background-color: #d0d0d0; color: {_theme.COLOR_LINE}; }}
        """)
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_row.addWidget(self.clear_filters_btn)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.stats_label = QLabel("Showing 0 of 0 channels")
        self.stats_label.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: 12px;")

    # ── Source chips ──────────────────────────────────────────────────────────

    def update_source_chips(self, providers: list):
        """Rebuild source filter chips from the list of active Provider/ProviderDB objects.

        Each element should have .id, .name, and optionally .icon attributes.
        The row is hidden when len(providers) <= 1.
        """
        # Remove all old chips (keep label + stretch)
        for chip in self._source_chips.values():
            self._source_chips_layout.removeWidget(chip)
            chip.deleteLater()
        self._source_chips.clear()

        if len(providers) <= 1:
            self._source_row_widget.hide()
            return

        # Re-insert chips before the stretch
        stretch_index = self._source_chips_layout.count() - 1  # last item is stretch
        for provider in providers:
            icon = getattr(provider, 'icon', '') or ''
            name = getattr(provider, 'name', str(provider))
            label = f"{icon} {name}".strip() if icon else name
            chip = ToggleChip(label, enabled=True)
            chip.setProperty("provider_id", provider.id)
            chip.toggled_changed.connect(self.on_filter_changed)
            self._source_chips_layout.insertWidget(stretch_index, chip)
            stretch_index += 1
            self._source_chips[provider.id] = chip

        self._source_row_widget.setVisible(True)

    def get_excluded_provider_ids(self) -> List[str]:
        """Return provider IDs whose source chip is deselected."""
        return [pid for pid, chip in self._source_chips.items() if not chip.is_enabled()]

    # ── Filter groups ─────────────────────────────────────────────────────────

    def update_filter_groups(self, language_groups: Dict[str, int],
                             quality_groups: Dict[str, int],
                             platform_groups: Dict[str, int] | None = None,
                             region_groups: Dict[str, int] | None = None):
        """Update all filter dropdowns; auto-hide when empty."""
        self.language_dropdown.update_groups(language_groups)
        self.quality_dropdown.update_groups(quality_groups)
        has_quality = any(v > 0 for v in quality_groups.values())
        self.quality_dropdown.setVisible(has_quality)
        if platform_groups is not None:
            self.platform_dropdown.update_groups(platform_groups)
            has_platform = any(v > 0 for v in platform_groups.values())
            self.platform_dropdown.setVisible(has_platform)
        if region_groups is not None:
            self.region_dropdown.update_groups(region_groups)
            has_region = any(v > 0 for v in region_groups.values())
            self.region_dropdown.setVisible(has_region)

    # ── Filter state ──────────────────────────────────────────────────────────

    def update_stats(self, shown: int, total: int, filtered: int):
        self.stats_label.setText(f"Showing {shown:,} of {total:,} · {filtered:,} filtered out")

    def get_filter_state(self) -> Dict:
        return {
            'media_types': [],  # managed by MainWindow chips
            'language_groups': self.language_dropdown.get_selected(),
            'region_groups': self.region_dropdown.get_selected(),
            'quality_groups': self.quality_dropdown.get_selected(),
            'platform_groups': self.platform_dropdown.get_selected(),
            'show_excluded': False,  # removed — use Global Exclusions for blacklisting
            'include_untagged': self.include_untagged_check.isChecked(),
            'adult_mode': ['all', 'hide', 'only'][self.adult_mode_combo.currentIndex()],
            'excluded_provider_ids': self.get_excluded_provider_ids(),
        }

    def on_filter_changed(self):
        logger.debug(f"Filter changed: {self.get_filter_state()}")
        if not self._restoring_state:
            self.save_state()
        self.filter_changed.emit()

    def clear_filters(self):
        """Reset all filters to default (all enabled)."""
        if self.parent():
            parent = self.parent()
            for attr in ('live_chip', 'movies_chip', 'series_chip'):
                chip = getattr(parent, attr, None)
                if chip:
                    chip.set_enabled(True)

        self.language_dropdown.blockSignals(True)
        self.region_dropdown.blockSignals(True)
        self.quality_dropdown.blockSignals(True)
        self.platform_dropdown.blockSignals(True)
        self.language_dropdown.select_all()
        self.region_dropdown.select_all()
        self.quality_dropdown.select_all()
        self.platform_dropdown.select_all()
        self.language_dropdown.blockSignals(False)
        self.region_dropdown.blockSignals(False)
        self.quality_dropdown.blockSignals(False)
        self.platform_dropdown.blockSignals(False)

        self.include_untagged_check.blockSignals(True)
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.blockSignals(False)

        self.adult_mode_combo.blockSignals(True)
        self.adult_mode_combo.setCurrentIndex(1)  # "Hide adult"
        self.adult_mode_combo.blockSignals(False)

        for chip in self._source_chips.values():
            chip.set_enabled(True)

        logger.info("Filters cleared — all enabled")
        self.save_state()
        self.filter_changed.emit()

    def save_state(self):
        try:
            state = self.get_filter_state()
            if self.parent() and hasattr(self.parent(), 'get_enabled_media_types'):
                state['media_types'] = self.parent().get_enabled_media_types()

            self.config.filter_enabled_media_types = state['media_types']
            self.config.filter_included_languages = state['language_groups']
            self.config.filter_included_regions = state['region_groups']
            self.config.filter_included_qualities = state['quality_groups']
            self.config.filter_included_platforms = state['platform_groups']
            self.config.filter_include_untagged = state['include_untagged']
            self.config.filter_adult_mode = state['adult_mode']
            self.config.save()
            logger.debug(f"Saved filter state: {state}")
        except Exception as e:
            logger.warning(f"Could not save filter state: {e}")

    def restore_state(self):
        self._restoring_state = True
        try:
            included_languages = getattr(self.config, 'filter_included_languages', [])
            if included_languages:
                self.language_dropdown.selected_groups = set(included_languages)

            included_regions = getattr(self.config, 'filter_included_regions', [])
            if included_regions:
                self.region_dropdown.selected_groups = set(included_regions)

            included_qualities = getattr(self.config, 'filter_included_qualities', [])
            if included_qualities:
                self.quality_dropdown.selected_groups = set(included_qualities)

            included_platforms = getattr(self.config, 'filter_included_platforms', [])
            if included_platforms:
                self.platform_dropdown.selected_groups = set(included_platforms)

            include_untagged = getattr(self.config, 'filter_include_untagged', True)
            self.include_untagged_check.setChecked(include_untagged)

            adult_mode = getattr(self.config, 'filter_adult_mode', 'hide')
            idx = {'all': 0, 'hide': 1, 'only': 2}.get(adult_mode, 1)
            self.adult_mode_combo.setCurrentIndex(idx)

            logger.info("Restored filter state")
        except Exception as e:
            logger.warning(f"Could not restore filter state: {e}")
        finally:
            self._restoring_state = False

    def set_adult_filter_visible(self, visible: bool) -> None:
        """Show or hide the adult content filter based on whether adult channels exist."""
        self._adult_filter_widget.setVisible(visible)

    def get_enabled_media_types(self) -> List[str]:
        """Kept for backwards compatibility."""
        return []
