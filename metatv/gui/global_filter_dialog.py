"""Global Exclusions dialog.

Shows every prefix detected in the DB with its channel count. Prefixes are
grouped under language-group headings as a visual hint (not a truth). Groups
start collapsed; prefix checkboxes are built lazily on first expand so the
dialog opens instantly regardless of how many prefixes exist in the DB.

Opt-out blacklist model: checkboxes start unchecked (nothing excluded).
Checking a group/prefix HIDES it from Discovery, Recommendations, and all
other views. Empty exclusion list = show everything (the default).

Settings persist to config.global_filter_excluded_categories (list of
excluded prefix codes, e.g. ["AR", "KU"]).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database


def _load_source_category_counts(db: Database) -> list[tuple[str, int]]:
    """Return [(source_category, count)] for live channels with a known source_category."""
    from sqlalchemy import func
    from metatv.core.database import ChannelDB
    session = db.get_session()
    try:
        rows = (
            session.query(ChannelDB.source_category, func.count())
            .filter(
                ChannelDB.source_category.isnot(None),
                ChannelDB.media_type == "live",
            )
            .group_by(ChannelDB.source_category)
            .all()
        )
        return [(row[0], row[1]) for row in rows if row[0]]
    finally:
        session.close()


def _load_prefix_counts(db: Database) -> list[tuple[str, int]]:
    """Return [(prefix, count)] for all prefixes in the DB, sorted alphabetically."""
    from sqlalchemy import func
    from metatv.core.database import ChannelDB
    session = db.get_session()
    try:
        rows = (
            session.query(ChannelDB.detected_prefix, func.count())
            .filter(
                ChannelDB.detected_prefix.isnot(None),
                ChannelDB.media_type.in_(["movie", "series", "live"]),
            )
            .group_by(ChannelDB.detected_prefix)
            .order_by(ChannelDB.detected_prefix)
            .all()
        )
        return [(row[0], row[1]) for row in rows if row[0]]
    finally:
        session.close()


def _group_prefixes(
    prefix_counts: list[tuple[str, int]],
    language_groups: dict[str, list[str]],
) -> list[tuple[str, list[tuple[str, int]]]]:
    """Group prefixes under language group names; unmatched go in 'Other'.

    Returns [(group_name, [(prefix, count)]), …] — named groups sorted
    alphabetically, 'Other' last.
    """
    prefix_upper_map: dict[str, tuple[str, int]] = {
        p.upper(): (p, c) for p, c in prefix_counts
    }
    remaining = set(prefix_upper_map.keys())

    named: dict[str, list[tuple[str, int]]] = {}
    for group_name, members in language_groups.items():
        matched = []
        for m in members:
            key = m.upper()
            if key in remaining:
                matched.append(prefix_upper_map[key])
                remaining.discard(key)
        if matched:
            named[group_name] = sorted(matched, key=lambda x: x[0])

    result = [(g, named[g]) for g in sorted(named)]
    if remaining:
        other = sorted([prefix_upper_map[k] for k in remaining], key=lambda x: x[0])
        result.append(("Other", other))
    return result


class _GroupSection(QWidget):
    """Collapsible group section. Header built eagerly; prefix rows built lazily
    on first expand so the dialog opens fast regardless of prefix count."""

    def __init__(
        self,
        group_name: str,
        prefixes: list[tuple[str, int]],
        initially_checked: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._group_name = group_name
        self._prefix_data = prefixes                    # raw data, always present
        self._initial_checked = {s.upper() for s in initially_checked}
        self._checkboxes: dict[str, QCheckBox] = {}    # built lazily
        self._body_built = False
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 4)

        # ── Header row (always created) ───────────────────────────────────────
        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(6)

        self._group_cb = QCheckBox()
        self._group_cb.setTristate(True)
        self._group_cb.setStyleSheet("font-size: 12px;")
        hl.addWidget(self._group_cb)

        self._expand_lbl = QLabel("▶")
        self._expand_lbl.setStyleSheet("color: #666; font-size: 9px;")
        self._expand_lbl.setFixedWidth(12)
        hl.addWidget(self._expand_lbl)

        name_lbl = QLabel(group_name)
        name_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        hl.addWidget(name_lbl)
        hl.addStretch()

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet("color: #666; font-size: 11px;")
        hl.addWidget(self._count_lbl)

        layout.addWidget(header)

        # ── Body placeholder (empty until first expand) ───────────────────────
        self._body = QWidget()
        self._body.setVisible(False)
        layout.addWidget(self._body)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        self._group_cb.stateChanged.connect(self._on_group_changed)
        header.mousePressEvent = self._toggle_expand  # type: ignore[assignment]

        self._update_group_state()

    # ── Lazy body construction ─────────────────────────────────────────────────

    def _build_body(self) -> None:
        body_vl = QVBoxLayout(self._body)
        body_vl.setSpacing(2)
        body_vl.setContentsMargins(28, 2, 0, 4)

        for prefix, count in self._prefix_data:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            cb = QCheckBox(prefix)
            cb.setChecked(prefix.upper() in self._initial_checked)
            cb.setStyleSheet("font-size: 12px; font-family: monospace;")
            cb.stateChanged.connect(self._on_prefix_changed)
            rl.addWidget(cb)

            count_lbl = QLabel(f"({count:,})")
            count_lbl.setStyleSheet("color: #666; font-size: 11px;")
            rl.addWidget(count_lbl)
            rl.addStretch()

            body_vl.addWidget(row)
            self._checkboxes[prefix] = cb

        self._body_built = True

    # ── Public state API ──────────────────────────────────────────────────────

    def all_prefixes(self) -> list[str]:
        return [p for p, _ in self._prefix_data]

    def checked_prefixes(self) -> list[str]:
        if self._body_built:
            return [p for p, cb in self._checkboxes.items() if cb.isChecked()]
        return [p for p, _ in self._prefix_data if p.upper() in self._initial_checked]

    def set_all(self, checked: bool) -> None:
        if self._body_built:
            for cb in self._checkboxes.values():
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        else:
            if checked:
                self._initial_checked = {p.upper() for p, _ in self._prefix_data}
            else:
                self._initial_checked = set()
        self._update_group_state()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _toggle_expand(self, _event=None) -> None:
        self._expanded = not self._expanded
        if self._expanded and not self._body_built:
            self._build_body()
        self._body.setVisible(self._expanded)
        self._expand_lbl.setText("▼" if self._expanded else "▶")

    def _update_group_state(self) -> None:
        total = len(self._prefix_data)
        if self._body_built:
            checked = sum(1 for cb in self._checkboxes.values() if cb.isChecked())
        else:
            checked = sum(
                1 for p, _ in self._prefix_data if p.upper() in self._initial_checked
            )
        self._count_lbl.setText(f"[{checked} of {total}]")

        self._group_cb.blockSignals(True)
        if checked == 0:
            self._group_cb.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total:
            self._group_cb.setCheckState(Qt.CheckState.Checked)
        else:
            self._group_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._group_cb.blockSignals(False)

    def _on_prefix_changed(self) -> None:
        self._update_group_state()

    def _on_group_changed(self, state: int) -> None:
        qt_state = Qt.CheckState(state)
        if qt_state == Qt.CheckState.PartiallyChecked:
            return
        checked = qt_state == Qt.CheckState.Checked
        if self._body_built:
            for cb in self._checkboxes.values():
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        else:
            if checked:
                self._initial_checked = {p.upper() for p, _ in self._prefix_data}
            else:
                self._initial_checked = set()
        self._update_group_state()


class _RescanThread(QThread):
    """Background thread that re-runs prefix detection on all channels."""
    done = pyqtSignal(int)

    def __init__(self, db: Database, separators: list[str], parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._separators = separators

    def run(self) -> None:
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            updated = repos.channels.update_detected_prefixes(separators=self._separators)
            self.done.emit(updated)
        except Exception as exc:
            logger.error(f"Prefix re-scan failed: {exc}")
            self.done.emit(0)
        finally:
            session.close()


class GlobalFilterDialog(QDialog):
    """Modal dialog for setting global content category filters."""

    def __init__(self, db: Database, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._sections: list[_GroupSection] = []
        self._inner_vl: QVBoxLayout | None = None
        self._rescan_thread: _RescanThread | None = None
        # Content-type section: list of (group_name, checkbox, row_widget)
        self._content_type_rows: list[tuple[str, QCheckBox, QWidget]] = []
        # Separator / header widgets for the content-type section
        self._content_type_header_widgets: list[QWidget] = []

        self.setWindowTitle("Exclusions")
        self.setMinimumSize(420, 540)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_lbl = QLabel("Global Exclusions")
        header_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_row.addWidget(header_lbl)

        info_lbl = QLabel("ⓘ")
        info_lbl.setStyleSheet("color: #888; font-size: 12px; padding-left: 4px;")
        info_lbl.setToolTip(
            "Categories are detected from the prefix in each title\n"
            "(e.g. 'AR Drama', 'DE Movies'). Group headings are\n"
            "best-guess language/region hints — not guaranteed to be correct.\n"
            "Expand a group to see and control individual prefix codes."
        )
        header_row.addWidget(info_lbl)
        header_row.addStretch()
        vl.addLayout(header_row)

        hint = QLabel(
            "Check categories to hide them everywhere — Discovery, Recommendations, and search.\n"
            "Nothing checked = show all content. Expand a group to control individual prefixes."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        vl.addWidget(hint)

        # ── Scrollable group list ──────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        self._inner_vl = QVBoxLayout(inner)
        self._inner_vl.setSpacing(0)
        self._inner_vl.setContentsMargins(4, 4, 4, 4)

        self._populate_groups()

        self._inner_vl.addStretch()
        scroll.setWidget(inner)
        vl.addWidget(scroll)

        # ── Include uncategorized ──────────────────────────────────────────────
        self._uncat_cb = QCheckBox("Hide content with no category label")
        # Blacklist semantics: checked = hide untagged (include_uncategorized = False)
        self._uncat_cb.setChecked(not self._config.global_filter_include_uncategorized)
        self._uncat_cb.setStyleSheet("font-size: 12px; color: #aaa; padding-top: 4px;")
        self._uncat_cb.setToolTip(
            "Content with no detected category prefix is usually general/English-language.\n"
            "Leave unchecked to keep it visible (the safe default)."
        )
        vl.addWidget(self._uncat_cb)

        # ── Globally hidden categories (explicit blocklist) ────────────────────
        self._hidden_row = QWidget()
        hidden_hl = QHBoxLayout(self._hidden_row)
        hidden_hl.setContentsMargins(0, 4, 0, 0)
        hidden_hl.setSpacing(4)
        hidden_hl.addWidget(QLabel("Globally hidden:"))
        self._hidden_chips_widget = QWidget()
        self._hidden_chips_layout = QHBoxLayout(self._hidden_chips_widget)
        self._hidden_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._hidden_chips_layout.setSpacing(4)
        hidden_hl.addWidget(self._hidden_chips_widget)
        hidden_hl.addStretch()
        self._hidden_row.setToolTip(
            "These prefixes were explicitly hidden via the 'Hide the category' action.\n"
            "Click × to restore a category to the filter options."
        )
        self._rebuild_hidden_chips()
        vl.addWidget(self._hidden_row)

        # ── Select all / none + Re-scan ────────────────────────────────────────
        shortcut_row = QHBoxLayout()
        for label, checked in [("Select all", True), ("Select none", False)]:
            btn = QLabel(f'<a href="{label}" style="color:#4488ff;">{label}</a>')
            btn.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            btn.linkActivated.connect(lambda _, c=checked: self._select_all(c))
            shortcut_row.addWidget(btn)
        shortcut_row.addStretch()

        self._rescan_btn = QPushButton("Re-scan Prefixes")
        self._rescan_btn.setFlat(True)
        self._rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rescan_btn.setStyleSheet("font-size: 11px; color: #666;")
        self._rescan_btn.setToolTip(
            "Re-detect prefix codes for all channels using the current separator settings.\n"
            "Useful after adding a new source with a different naming convention."
        )
        self._rescan_btn.clicked.connect(self._start_rescan)
        shortcut_row.addWidget(self._rescan_btn)

        reset_btn = QPushButton("Reset Category Overrides")
        reset_btn.setFlat(True)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet("font-size: 11px; color: #a66;")
        reset_btn.setToolTip(
            "Clear all your custom category assignments and restore built-in defaults.\n"
            "Provider-specific overrides are not affected."
        )
        reset_btn.clicked.connect(self._reset_user_overrides)
        shortcut_row.addWidget(reset_btn)

        vl.addLayout(shortcut_row)

        # ── OK / Cancel ────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    # ── Hidden categories management ──────────────────────────────────────────

    def _rebuild_hidden_chips(self) -> None:
        """Rebuild the hidden-prefixes chip row from current config state."""
        while self._hidden_chips_layout.count():
            item = self._hidden_chips_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        hidden = list(self._config.global_filter_excluded_prefixes)
        self._hidden_row.setVisible(bool(hidden))
        for prefix in hidden:
            chip = QPushButton(f"{prefix} ×")
            chip.setFlat(True)
            chip.setStyleSheet(
                "QPushButton { font-size: 11px; color: #888; border: 1px solid #444;"
                " border-radius: 3px; padding: 1px 6px; }"
                "QPushButton:hover { color: #ccc; border-color: #666; }"
            )
            chip.setToolTip(f"Click to restore {prefix} — will appear in Content Categories again")
            chip.clicked.connect(lambda _, p=prefix: self._unhide_prefix(p))
            self._hidden_chips_layout.addWidget(chip)

    def _unhide_prefix(self, prefix: str) -> None:
        if prefix in self._config.global_filter_excluded_prefixes:
            self._config.global_filter_excluded_prefixes.remove(prefix)
        self._rebuild_hidden_chips()

    # ── Group population helpers ───────────────────────────────────────────────

    def _populate_groups(self) -> None:
        """Build group section widgets from current DB prefix data."""
        # Blacklist model: currently excluded prefixes start checked; everything else unchecked.
        excluded = set(self._config.global_filter_excluded_categories)

        prefix_counts = _load_prefix_counts(self._db)
        all_groups = _group_prefixes(prefix_counts, self._config.filter_language_groups)
        logger.debug(
            f"GlobalFilterDialog: {len(prefix_counts)} prefixes in {len(all_groups)} groups"
        )

        named_groups = [(n, p) for n, p in all_groups if n != "Other"]
        other_entries = next((p for n, p in all_groups if n == "Other"), [])

        for group_name, prefixes in named_groups:
            # Only pre-check prefixes that are currently excluded
            initial = excluded & {p for p, _ in prefixes}
            section = _GroupSection(group_name, prefixes, initial)
            self._inner_vl.addWidget(section)
            self._sections.append(section)

        if other_entries:
            initial = excluded & {p for p, _ in other_entries}
            other_section = _GroupSection("Other", other_entries, initial)
            self._inner_vl.addWidget(other_section)
            self._sections.append(other_section)

        self._populate_content_types()

    def _populate_content_types(self) -> None:
        """Build the Content Types section below the prefix groups."""
        cat_counts = _load_source_category_counts(self._db)
        if not cat_counts:
            return

        groups = self._config.content_category_groups
        group_counts: dict[str, int] = {}
        matched_labels: set[str] = set()

        for group_name, raw_labels in groups.items():
            raw_upper = {lbl.upper() for lbl in raw_labels}
            total = sum(c for lbl, c in cat_counts if lbl.upper() in raw_upper)
            if total > 0:
                group_counts[group_name] = total
                matched_labels.update(lbl for lbl, _ in cat_counts if lbl.upper() in raw_upper)

        other_count = sum(c for lbl, c in cat_counts if lbl not in matched_labels)

        if not group_counts and not other_count:
            return

        # ── Separator ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444; margin-top: 4px; margin-bottom: 4px;")
        self._inner_vl.addWidget(sep)
        self._content_type_header_widgets.append(sep)

        hdr_row = QHBoxLayout()
        type_hdr = QLabel("Content Types")
        type_hdr.setStyleSheet("font-size: 12px; font-weight: bold; padding-top: 4px;")
        hdr_row.addWidget(type_hdr)

        info_lbl = QLabel("ⓘ")
        info_lbl.setStyleSheet("color: #888; font-size: 12px; padding-left: 4px; padding-top: 4px;")
        info_lbl.setToolTip(
            "Content types are derived from category headers in the provider's\n"
            "channel list (e.g. ##### SPORTS NETWORK #####).\n"
            "Uncheck a type to hide all matching live channels from Discovery."
        )
        hdr_row.addWidget(info_lbl)
        hdr_row.addStretch()

        hdr_container = QWidget()
        hdr_container.setLayout(hdr_row)
        self._inner_vl.addWidget(hdr_container)
        self._content_type_header_widgets.append(hdr_container)

        # Blacklist model: checked = excluded; start unchecked unless currently excluded.
        excluded_types = set(self._config.global_filter_excluded_content_types)

        for group_name in sorted(group_counts):
            count = group_counts[group_name]
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)

            cb = QCheckBox(group_name)
            cb.setChecked(group_name in excluded_types)
            cb.setStyleSheet("font-size: 12px;")
            rl.addWidget(cb)

            count_lbl = QLabel(f"({count:,} channels)")
            count_lbl.setStyleSheet("color: #666; font-size: 11px;")
            rl.addWidget(count_lbl)
            rl.addStretch()

            self._inner_vl.addWidget(row)
            self._content_type_rows.append((group_name, cb, row))

        if other_count:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)

            cb = QCheckBox("Other (unmapped types)")
            cb.setChecked("_other_" in excluded_types)
            cb.setStyleSheet("font-size: 12px; color: #aaa;")
            cb.setToolTip(
                "Live channels whose category header didn't match any\n"
                "configured Content Type group."
            )
            rl.addWidget(cb)

            count_lbl = QLabel(f"({other_count:,} channels)")
            count_lbl.setStyleSheet("color: #666; font-size: 11px;")
            rl.addWidget(count_lbl)
            rl.addStretch()

            self._inner_vl.addWidget(row)
            self._content_type_rows.append(("_other_", cb, row))

    def _clear_groups(self) -> None:
        """Remove all group widgets (before a re-populate)."""
        for section in self._sections:
            self._inner_vl.removeWidget(section)
            section.deleteLater()
        self._sections.clear()

        for _name, _cb, row in self._content_type_rows:
            self._inner_vl.removeWidget(row)
            row.deleteLater()
        self._content_type_rows.clear()

        for w in self._content_type_header_widgets:
            self._inner_vl.removeWidget(w)
            w.deleteLater()
        self._content_type_header_widgets.clear()

    # ── Re-scan ────────────────────────────────────────────────────────────────

    def _start_rescan(self) -> None:
        self._rescan_btn.setEnabled(False)
        self._rescan_btn.setText("Scanning…")
        self._rescan_thread = _RescanThread(
            self._db, self._config.prefix_separators, parent=self
        )
        self._rescan_thread.done.connect(self._on_rescan_done)
        self._rescan_thread.start()

    def _on_rescan_done(self, updated: int) -> None:
        logger.info(f"Dialog re-scan complete: {updated} channels updated")
        self._rescan_btn.setText("Re-scan Prefixes")
        self._rescan_btn.setEnabled(True)
        # Remove trailing stretch, repopulate, re-add stretch
        stretch_idx = self._inner_vl.count() - 1
        self._inner_vl.takeAt(stretch_idx)
        self._clear_groups()
        self._populate_groups()
        self._inner_vl.addStretch()

    # ── Actions ────────────────────────────────────────────────────────────────

    def _reset_user_overrides(self) -> None:
        """Clear user_prefix_overrides and re-render — groups revert to built-in defaults."""
        self._config.user_prefix_overrides.clear()
        self._config.save()
        stretch_idx = self._inner_vl.count() - 1
        self._inner_vl.takeAt(stretch_idx)
        self._clear_groups()
        self._populate_groups()
        self._inner_vl.addStretch()
        logger.info("User category overrides reset to defaults")

    def _select_all(self, checked: bool) -> None:
        for section in self._sections:
            section.set_all(checked)
        for _name, cb, _row in self._content_type_rows:
            cb.setChecked(checked)

    def _save_and_accept(self) -> None:
        # Blacklist model: save checked prefixes as excluded (checked = hidden).
        excluded_prefixes = [p for s in self._sections for p in s.checked_prefixes()]
        self._config.global_filter_excluded_categories = excluded_prefixes

        # "Hide untagged" checkbox: checked = hide = include_uncategorized False
        self._config.global_filter_include_uncategorized = not self._uncat_cb.isChecked()

        # Content type exclusions: checked = excluded
        excluded_types = [name for name, cb, _row in self._content_type_rows if cb.isChecked()]
        self._config.global_filter_excluded_content_types = excluded_types

        self._config.save()
        self.accept()
