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
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme


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


def _load_tag_content_type_counts(db: Database, values: list[str]) -> dict[str, int]:
    """Return ``{content_type_value: distinct_channel_count}`` for *values*.

    Counts channels carrying each ``content_type`` tag (any source — generated or
    user) among *values*.  A tiny, tag_id-indexed lookup (never a full channels
    scan), so it loads synchronously in the dialog exactly like the sibling
    prefix / source-category counts.  Values absent from the result carry 0.
    """
    from sqlalchemy import func
    from metatv.core.database import ContentTagDB, TagDB
    if not values:
        return {}
    session = db.get_session()
    try:
        rows = (
            session.query(
                TagDB.value,
                func.count(func.distinct(ContentTagDB.channel_id)),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(TagDB.type == "content_type", TagDB.value.in_(values))
            .group_by(TagDB.value)
            .all()
        )
        return {value: count for value, count in rows}
    finally:
        session.close()


def _load_prefix_counts(db: Database, excluded_user_categories: set[str] | None = None) -> list[tuple[str, int]]:
    """Return [(prefix, count)] for all prefixes in the DB, sorted alphabetically."""
    from sqlalchemy import func
    from metatv.core.database import ChannelDB
    session = db.get_session()
    try:
        q = (
            session.query(ChannelDB.detected_prefix, func.count())
            .filter(
                ChannelDB.detected_prefix.isnot(None),
                ChannelDB.media_type.in_(["movie", "series", "live"]),
            )
        )
        if excluded_user_categories:
            from sqlalchemy import or_ as _or
            q = q.filter(_or(ChannelDB.user_category.is_(None),
                             ~ChannelDB.user_category.in_(excluded_user_categories)))
        rows = (
            q.group_by(ChannelDB.detected_prefix)
            .order_by(ChannelDB.detected_prefix)
            .all()
        )
        return [(row[0], row[1]) for row in rows if row[0]]
    finally:
        session.close()


def _group_prefixes(
    prefix_counts: list[tuple[str, int]],
    language_groups: dict[str, list[str]],
    platform_groups: dict[str, list[str]] | None = None,
) -> list[tuple[str, list[tuple[str, int]]]]:
    """Group prefixes under language/platform group names; unmatched go in 'Uncategorized'.

    Returns [(group_name, [(prefix, count)]), …] — named groups sorted
    alphabetically, 'Uncategorized' last.
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

    # Also consume platform group codes so they don't appear in Uncategorized.
    # Platform codes (NF, D+, etc.) are properly labelled in the filter panel's
    # Platform section; they should not bleed into Uncategorized here.
    if platform_groups:
        for group_name, members in platform_groups.items():
            for m in members:
                remaining.discard(m.upper())

    result = [(g, named[g]) for g in sorted(named)]
    if remaining:
        other = sorted([prefix_upper_map[k] for k in remaining], key=lambda x: x[0])
        result.append(("Uncategorized", other))
    return result


class _GroupSection(QWidget):
    """Collapsible group section. Header built eagerly; prefix rows built lazily
    on first expand so the dialog opens fast regardless of prefix count."""

    def __init__(
        self,
        group_name: str,
        prefixes: list[tuple[str, int]],
        initially_checked: set[str],
        *,
        config,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
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
        cursor_affordance.set_clickable(header)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(6)

        self._group_cb = QCheckBox()
        self._group_cb.setTristate(True)
        self._group_cb.setStyleSheet(_theme.FILTER_ITEM_TEXT)
        hl.addWidget(self._group_cb)

        self._expand_lbl = QLabel(config.expand_icon)
        self._expand_lbl.setStyleSheet(_theme.EXPAND_HINT)
        self._expand_lbl.setFixedWidth(12)
        hl.addWidget(self._expand_lbl)

        name_lbl = QLabel(group_name)
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_LG}; font-weight: bold;")
        hl.addWidget(name_lbl)
        hl.addStretch()

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(_theme.LABEL_MUTED)
        hl.addWidget(self._count_lbl)

        layout.addWidget(header)

        # ── Body placeholder (empty until first expand) ───────────────────────
        self._body = QWidget()
        self._body.setVisible(False)
        layout.addWidget(self._body)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        layout.addWidget(sep)

        self._group_cb.clicked.connect(self._on_group_clicked)
        header.mousePressEvent = self._toggle_expand  # type: ignore[assignment]

        self._update_group_state()

    # ── Lazy body construction ─────────────────────────────────────────────────

    def _build_body(self) -> None:
        from metatv.core.channel_name_utils import REGION_FULL_NAMES

        body_vl = QVBoxLayout(self._body)
        body_vl.setSpacing(2)
        body_vl.setContentsMargins(28, 2, 0, 4)

        for prefix, count in self._prefix_data:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            full_name = REGION_FULL_NAMES.get(prefix.upper(), "")
            label = f"[{prefix}] {full_name}" if full_name else prefix
            cb = QCheckBox(label)
            cb.setChecked(prefix.upper() in self._initial_checked)
            cb.setStyleSheet(f"font-size: {_theme.FONT_LG}; font-family: monospace;")
            cb.stateChanged.connect(self._on_prefix_changed)
            rl.addWidget(cb)

            count_lbl = QLabel(f"({count:,})")
            count_lbl.setStyleSheet(_theme.LABEL_MUTED)
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
        glyph = self._config.collapse_icon if self._expanded else self._config.expand_icon
        self._expand_lbl.setText(glyph)

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

    def _on_group_clicked(self) -> None:
        """Handle user click on group checkbox — always binary, never PartiallyChecked via click.

        Tristate cycles Unchecked→Partial→Checked. We skip Partial: clicking an
        empty or partial group always escalates to fully checked; clicking a fully
        checked group unchecks all.
        """
        state = self._group_cb.checkState()
        if state == Qt.CheckState.PartiallyChecked:
            # Skip partial — escalate to fully checked
            self._group_cb.blockSignals(True)
            self._group_cb.setCheckState(Qt.CheckState.Checked)
            self._group_cb.blockSignals(False)
            state = Qt.CheckState.Checked
        checked = (state == Qt.CheckState.Checked)
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


class _ContentTypeSection(QWidget):
    """Collapsible section for unmapped source_category labels inside 'Other'.

    Identical collapse/expand and lazy-body pattern to _GroupSection but for
    raw source_category strings (which can be long provider labels, not codes).
    """

    def __init__(
        self,
        items: list[tuple[str, int]],       # [(source_category_label, count)]
        initially_checked: set[str],
        *,
        config,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._items = items
        self._initial_checked = {s for s in initially_checked}
        self._checkboxes: dict[str, QCheckBox] = {}
        self._body_built = False
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 4)

        # ── Header ────────────────────────────────────────────────────────────
        header = QWidget()
        cursor_affordance.set_clickable(header)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(6)

        self._group_cb = QCheckBox()
        self._group_cb.setTristate(True)
        self._group_cb.setStyleSheet(_theme.FILTER_ITEM_TEXT)
        hl.addWidget(self._group_cb)

        self._expand_lbl = QLabel(config.expand_icon)
        self._expand_lbl.setStyleSheet(_theme.EXPAND_HINT)
        self._expand_lbl.setFixedWidth(12)
        hl.addWidget(self._expand_lbl)

        name_lbl = QLabel("Other (unmapped types)")
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_LG}; font-weight: bold; color: {_theme.COLOR_DIM};")
        name_lbl.setToolTip(
            "Live channels whose source_category header from the provider\n"
            "didn't match any configured Content Type group.\n"
            "Expand to see individual category labels and exclude specific ones."
        )
        hl.addWidget(name_lbl)
        hl.addStretch()

        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet(_theme.LABEL_MUTED)
        hl.addWidget(self._count_lbl)

        layout.addWidget(header)

        self._body = QWidget()
        self._body.setVisible(False)
        layout.addWidget(self._body)

        self._group_cb.clicked.connect(self._on_group_clicked)
        header.mousePressEvent = self._toggle_expand  # type: ignore[assignment]

        self._update_state()

    def _build_body(self) -> None:
        body_vl = QVBoxLayout(self._body)
        body_vl.setSpacing(2)
        body_vl.setContentsMargins(28, 2, 0, 4)

        for label, count in sorted(self._items, key=lambda x: -x[1]):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            cb = QCheckBox(label)
            cb.setChecked(label in self._initial_checked)
            cb.setStyleSheet(f"font-size: {_theme.FONT_MD}; font-family: monospace;")
            cb.stateChanged.connect(self._on_item_changed)
            rl.addWidget(cb)

            cnt_lbl = QLabel(f"({count:,})")
            cnt_lbl.setStyleSheet(_theme.LABEL_MUTED)
            rl.addWidget(cnt_lbl)
            rl.addStretch()

            body_vl.addWidget(row)
            self._checkboxes[label] = cb

        self._body_built = True

    def checked_labels(self) -> list[str]:
        """Return list of individually checked source_category labels."""
        if self._body_built:
            return [lbl for lbl, cb in self._checkboxes.items() if cb.isChecked()]
        return [lbl for lbl, _ in self._items if lbl in self._initial_checked]

    def all_checked(self) -> bool:
        """True when every item in this section is checked."""
        checked = len(self.checked_labels())
        return checked == len(self._items)

    def set_all(self, checked: bool) -> None:
        if self._body_built:
            for cb in self._checkboxes.values():
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        else:
            self._initial_checked = {lbl for lbl, _ in self._items} if checked else set()
        self._update_state()

    def _toggle_expand(self, _event=None) -> None:
        self._expanded = not self._expanded
        if self._expanded and not self._body_built:
            self._build_body()
        self._body.setVisible(self._expanded)
        glyph = self._config.collapse_icon if self._expanded else self._config.expand_icon
        self._expand_lbl.setText(glyph)

    def _update_state(self) -> None:
        total = len(self._items)
        checked = len(self.checked_labels())
        self._count_lbl.setText(f"[{checked} of {total}]")

        self._group_cb.blockSignals(True)
        if checked == 0:
            self._group_cb.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total:
            self._group_cb.setCheckState(Qt.CheckState.Checked)
        else:
            self._group_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._group_cb.blockSignals(False)

    def _on_item_changed(self) -> None:
        self._update_state()

    def _on_group_clicked(self) -> None:
        state = self._group_cb.checkState()
        if state == Qt.CheckState.PartiallyChecked:
            self._group_cb.blockSignals(True)
            self._group_cb.setCheckState(Qt.CheckState.Checked)
            self._group_cb.blockSignals(False)
            state = Qt.CheckState.Checked
        self.set_all(state == Qt.CheckState.Checked)


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
        # Per-type section tracking — drives the per-type "all / none" controls
        # (types are orthogonal axes: selecting all Languages must not touch Platforms).
        self._language_sections: list[_GroupSection] = []
        self._platform_sections: list[_GroupSection] = []
        self._inner_vl: QVBoxLayout | None = None
        self._rescan_thread: _RescanThread | None = None
        # Content-type section: list of (group_name, checkbox, row_widget)
        self._content_type_rows: list[tuple[str, QCheckBox, QWidget]] = []
        # Expandable "Other" section for unmapped source_category labels
        self._content_type_other_section: _ContentTypeSection | None = None
        # Separator / header widgets for the content-type section
        self._content_type_header_widgets: list[QWidget] = []
        # Separator / header widgets for the platforms section
        self._platform_header_widgets: list[QWidget] = []
        # User-defined category rows: list of (category_name, checkbox, row_widget)
        self._user_category_rows: list[tuple[str, QCheckBox, QWidget]] = []
        # Content-provenance rows: list of (content_type_slug, checkbox, row_widget)
        self._content_provenance_rows: list[tuple[str, QCheckBox, QWidget]] = []

        self.setWindowTitle("Exclusions")
        self.setMinimumSize(420, 540)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_lbl = QLabel("Global Exclusions")
        header_lbl.setStyleSheet(f"font-size: {_theme.FONT_XL}; font-weight: bold;")
        header_row.addWidget(header_lbl)

        info_lbl = QLabel("ⓘ")
        info_lbl.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_LG}; padding-left: 4px;")
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
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
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
        self._uncat_cb.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_DIM}; padding-top: 4px;")
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
            btn = QLabel(f'<a href="{label}" style="color:{_theme.COLOR_ACCENT_BLUE};">{label}</a>')
            btn.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            btn.linkActivated.connect(lambda _, c=checked: self._select_all(c))
            shortcut_row.addWidget(btn)
        shortcut_row.addStretch()

        self._rescan_btn = QPushButton("Re-scan Prefixes")
        self._rescan_btn.setFlat(True)
        self._rescan_btn.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_MUTED_2};")
        self._rescan_btn.setToolTip(
            "Re-detect prefix codes for all channels using the current separator settings.\n"
            "Useful after adding a new source with a different naming convention."
        )
        self._rescan_btn.clicked.connect(self._start_rescan)
        shortcut_row.addWidget(self._rescan_btn)

        reset_btn = QPushButton("Reset Category Overrides")
        reset_btn.setFlat(True)
        reset_btn.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_ERR_MUTED};")
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
                f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_MUTED}; border: 1px solid {_theme.COLOR_BORDER};"
                " border-radius: 3px; padding: 1px 6px; }"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; border-color: {_theme.COLOR_MUTED_2}; }}"
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

        prefix_counts = _load_prefix_counts(
            self._db,
            excluded_user_categories=set(self._config.global_filter_excluded_user_categories),
        )
        all_groups = _group_prefixes(
            prefix_counts,
            self._config.filter_language_groups,
            platform_groups=self._config.filter_platform_groups,
        )
        logger.debug(
            f"GlobalFilterDialog: {len(prefix_counts)} prefixes in {len(all_groups)} groups"
        )

        named_groups = [(n, p) for n, p in all_groups if n != "Uncategorized"]
        other_entries = next((p for n, p in all_groups if n == "Uncategorized"), [])

        # ── Languages header (with per-type select-all) ─────────────────────────
        if named_groups:
            lang_row = QHBoxLayout()
            lang_hdr = QLabel("Languages")
            lang_hdr.setStyleSheet(_theme.SECTION_TITLE_SM)
            lang_row.addWidget(lang_hdr)
            lang_info = QLabel("ⓘ")
            lang_info.setStyleSheet(_theme.INFO_LABEL)
            lang_info.setToolTip(
                "Language / region groups detected from channel name prefixes.\n"
                "Check a group to globally exclude its channels."
            )
            lang_row.addWidget(lang_info)
            lang_row.addStretch()
            lang_row.addWidget(self._make_select_links(
                "Languages", lambda c: self._select_sections(self._language_sections, c)
            ))
            lang_w = QWidget()
            lang_w.setLayout(lang_row)
            self._inner_vl.addWidget(lang_w)

        for group_name, prefixes in named_groups:
            # Only pre-check prefixes that are currently excluded
            initial = excluded & {p for p, _ in prefixes}
            section = _GroupSection(group_name, prefixes, initial, config=self._config)
            self._inner_vl.addWidget(section)
            self._sections.append(section)
            self._language_sections.append(section)

        # ── Platform sections ───────────────────────────────────────────────────
        prefix_upper_counts: dict[str, int] = {p.upper(): c for p, c in prefix_counts}

        platform_data: list[tuple[str, list[tuple[str, int]]]] = []
        for group_name, codes in self._config.filter_platform_groups.items():
            entries = [
                (c, prefix_upper_counts.get(c.upper(), 0))
                for c in codes
                if prefix_upper_counts.get(c.upper(), 0) > 0
            ]
            if entries:
                entries.sort(key=lambda x: -x[1])
                platform_data.append((group_name, entries))

        if platform_data:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(_theme.SEP_DARK)
            self._inner_vl.addWidget(sep)
            self._platform_header_widgets.append(sep)

            hdr_row = QHBoxLayout()
            hdr = QLabel("Platforms")
            hdr.setStyleSheet(_theme.SECTION_TITLE_SM)
            hdr_row.addWidget(hdr)
            info = QLabel("ⓘ")
            info.setStyleSheet(_theme.INFO_LABEL)
            info.setToolTip(
                "Streaming services and broadcast platforms detected from channel\n"
                "name prefixes (Netflix, Disney+, Sports, etc.).\n"
                "Check a platform to globally exclude its channels."
            )
            hdr_row.addWidget(info)
            hdr_row.addStretch()
            hdr_row.addWidget(self._make_select_links(
                "Platforms", lambda c: self._select_sections(self._platform_sections, c)
            ))
            hdr_w = QWidget()
            hdr_w.setLayout(hdr_row)
            self._inner_vl.addWidget(hdr_w)
            self._platform_header_widgets.append(hdr_w)

            for group_name, entries in sorted(platform_data):
                initial = excluded & {p for p, _ in entries}
                section = _GroupSection(group_name, entries, initial, config=self._config)
                self._inner_vl.addWidget(section)
                self._sections.append(section)
                self._platform_sections.append(section)

        # ── Uncategorized (truly unmapped prefixes) ─────────────────────────────
        if other_entries:
            initial = excluded & {p for p, _ in other_entries}
            other_section = _GroupSection("Uncategorized", other_entries, initial, config=self._config)
            self._inner_vl.addWidget(other_section)
            self._sections.append(other_section)

        self._populate_content_types()
        self._populate_content_provenance()
        self._populate_user_categories()

    def _populate_user_categories(self) -> None:
        """Build the User Categories section at the bottom of the filter list."""
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            all_cats = repos.channels.get_all_user_categories()
        finally:
            session.close()

        if not all_cats:
            return

        excluded = set(getattr(self._config, "global_filter_excluded_user_categories", []))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(_theme.SEP_DARK)
        self._inner_vl.addWidget(sep)
        self._content_type_header_widgets.append(sep)

        hdr_row = QHBoxLayout()
        hdr = QLabel("User Categories")
        hdr.setStyleSheet(_theme.SECTION_TITLE_SM)
        hdr_row.addWidget(hdr)
        info = QLabel("ⓘ")
        info.setStyleSheet(_theme.INFO_LABEL)
        info.setToolTip(
            "Categories you've created via right-click → Assign Category.\n"
            "Check a category to hide its channels everywhere (Global Exclusion)."
        )
        hdr_row.addWidget(info)
        hdr_row.addStretch()
        hdr_row.addWidget(self._make_select_links(
            "User Categories", self._select_user_categories
        ))
        hdr_w = QWidget()
        hdr_w.setLayout(hdr_row)
        self._inner_vl.addWidget(hdr_w)
        self._content_type_header_widgets.append(hdr_w)

        for cat in all_cats:
            name  = cat["name"]
            count = cat["count"]
            row   = QWidget()
            rl    = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)
            cb = QCheckBox(name)
            cb.setChecked(name in excluded)
            cb.setStyleSheet(_theme.FILTER_ITEM_TEXT)
            rl.addWidget(cb)
            count_lbl = QLabel(f"({count:,} channels)")
            count_lbl.setStyleSheet(_theme.LABEL_MUTED)
            rl.addWidget(count_lbl)
            rl.addStretch()
            self._inner_vl.addWidget(row)
            self._user_category_rows.append((name, cb, row))

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

        other_items = [(lbl, c) for lbl, c in cat_counts if lbl not in matched_labels]

        if not group_counts and not other_items:
            return

        # ── Separator ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(_theme.SEP_DARK)
        self._inner_vl.addWidget(sep)
        self._content_type_header_widgets.append(sep)

        hdr_row = QHBoxLayout()
        type_hdr = QLabel("Content Types")
        type_hdr.setStyleSheet(_theme.SECTION_TITLE_SM)
        hdr_row.addWidget(type_hdr)

        info_lbl = QLabel("ⓘ")
        info_lbl.setStyleSheet(_theme.INFO_LABEL)
        info_lbl.setToolTip(
            "Content types are derived from category headers in the provider's\n"
            "channel list (e.g. ##### SPORTS NETWORK #####).\n"
            "Check a type to hide all matching live channels from Discovery."
        )
        hdr_row.addWidget(info_lbl)
        hdr_row.addStretch()
        hdr_row.addWidget(self._make_select_links(
            "Content Types", self._select_content_types
        ))

        hdr_container = QWidget()
        hdr_container.setLayout(hdr_row)
        self._inner_vl.addWidget(hdr_container)
        self._content_type_header_widgets.append(hdr_container)

        # Blacklist model: checked = excluded; start unchecked unless currently excluded.
        excluded_types = set(self._config.global_filter_excluded_content_types)
        # Individually excluded source_category labels (from the expandable Other section)
        excluded_raw = set(getattr(self._config, "global_filter_excluded_source_categories", []))

        for group_name in sorted(group_counts):
            count = group_counts[group_name]
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)

            cb = QCheckBox(group_name)
            cb.setChecked(group_name in excluded_types)
            cb.setStyleSheet(_theme.FILTER_ITEM_TEXT)
            rl.addWidget(cb)

            count_lbl = QLabel(f"({count:,} channels)")
            count_lbl.setStyleSheet(_theme.LABEL_MUTED)
            rl.addWidget(count_lbl)
            rl.addStretch()

            self._inner_vl.addWidget(row)
            self._content_type_rows.append((group_name, cb, row))

        if other_items:
            # Expandable section — shows individual source_category labels with counts.
            # Sorted by channel count descending so the most common categories are visible first.
            self._content_type_other_section = _ContentTypeSection(
                items=sorted(other_items, key=lambda x: -x[1]),
                initially_checked=excluded_raw,
                config=self._config,
            )
            self._inner_vl.addWidget(self._content_type_other_section)
            self._content_type_header_widgets.append(self._content_type_other_section)

    def _populate_content_provenance(self) -> None:
        """Build the 'Content Provenance' section — ``content_type`` TAG exclusions.

        A distinct mechanism from Content Types above.  Content Types key off the
        provider's category HEADER (``source_category``); these rows match a
        channel's stored ``content_type`` TAG (a NOT-EXISTS over ``content_tags``),
        so a "Sports" here would mean something different from a "Sports" category
        group — hence the deliberate separation (never merge the two lists).

        Scope for now: the two AI-provenance values (``ai_generated`` /
        ``ai_voiceover``).  The section iterates a list, so more ``content_type``
        values can be surfaced later without a structural change.  A value is shown
        when it has channels OR is already excluded (so an active exclusion is never
        hidden); when none qualify the section is omitted entirely.
        """
        from metatv.core.channel_name_utils import (
            AI_GENERATED_VALUE, AI_VOICEOVER_VALUE, content_type_display,
        )

        provenance_values = [AI_GENERATED_VALUE, AI_VOICEOVER_VALUE]
        counts = _load_tag_content_type_counts(self._db, provenance_values)
        excluded = set(getattr(self._config, "global_filter_excluded_tag_content_types", []))
        visible = [
            v for v in provenance_values
            if counts.get(v, 0) > 0 or v in excluded
        ]
        if not visible:
            return

        # ── Separator ──────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(_theme.SEP_DARK)
        self._inner_vl.addWidget(sep)
        self._content_type_header_widgets.append(sep)

        hdr_row = QHBoxLayout()
        hdr = QLabel("Content Provenance")
        hdr.setStyleSheet(_theme.SECTION_TITLE_SM)
        hdr_row.addWidget(hdr)

        info_lbl = QLabel("ⓘ")
        info_lbl.setStyleSheet(_theme.INFO_LABEL)
        info_lbl.setToolTip(
            "How the content was produced, detected from a trailing marker on the\n"
            "channel/title name:\n"
            "  • \"(AI Generated)\" name suffix  →  AI Generated (the content itself)\n"
            "  • \"(AI)\" / Lektor (AI) suffix   →  AI Voiceover (an AI dub/narration)\n"
            "Check a type to hide all channels carrying that content_type tag —\n"
            "everywhere (search, Discovery, Recommendations, EPG)."
        )
        hdr_row.addWidget(info_lbl)
        hdr_row.addStretch()
        hdr_row.addWidget(self._make_select_links(
            "Content Provenance", self._select_content_provenance
        ))
        hdr_w = QWidget()
        hdr_w.setLayout(hdr_row)
        self._inner_vl.addWidget(hdr_w)
        self._content_type_header_widgets.append(hdr_w)

        for value in visible:
            count = counts.get(value, 0)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)

            cb = QCheckBox(content_type_display(value))
            cb.setChecked(value in excluded)
            cb.setStyleSheet(_theme.FILTER_ITEM_TEXT)
            rl.addWidget(cb)

            count_lbl = QLabel(f"({count:,} channels)")
            count_lbl.setStyleSheet(_theme.LABEL_MUTED)
            rl.addWidget(count_lbl)
            rl.addStretch()

            self._inner_vl.addWidget(row)
            self._content_provenance_rows.append((value, cb, row))

    def _clear_groups(self) -> None:
        """Remove all group widgets (before a re-populate)."""
        for section in self._sections:
            self._inner_vl.removeWidget(section)
            section.deleteLater()
        self._sections.clear()

        for w in self._platform_header_widgets:
            self._inner_vl.removeWidget(w)
            w.deleteLater()
        self._platform_header_widgets.clear()

        for _name, _cb, row in self._content_type_rows:
            self._inner_vl.removeWidget(row)
            row.deleteLater()
        self._content_type_rows.clear()

        for _slug, _cb, row in self._content_provenance_rows:
            self._inner_vl.removeWidget(row)
            row.deleteLater()
        self._content_provenance_rows.clear()

        if self._content_type_other_section is not None:
            self._content_type_other_section = None  # already in header_widgets, will be deleted below

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
        """Master select/deselect — every type at once (the bottom shortcut)."""
        self._select_sections(self._sections, checked)
        self._select_content_types(checked)
        self._select_content_provenance(checked)
        self._select_user_categories(checked)

    def _select_sections(self, sections: list["_GroupSection"], checked: bool) -> None:
        """Select/deselect every prefix in the given group sections (one type)."""
        for section in sections:
            section.set_all(checked)

    def _select_content_types(self, checked: bool) -> None:
        for _name, cb, _row in self._content_type_rows:
            cb.setChecked(checked)
        if self._content_type_other_section:
            self._content_type_other_section.set_all(checked)

    def _select_content_provenance(self, checked: bool) -> None:
        for _slug, cb, _row in self._content_provenance_rows:
            cb.setChecked(checked)

    def _select_user_categories(self, checked: bool) -> None:
        for _name, cb, _row in self._user_category_rows:
            cb.setChecked(checked)

    def _make_select_links(self, title: str, select_fn) -> QWidget:
        """A compact ``all · none`` link pair scoped to a single type.

        Types are orthogonal axes (DR-0005): each type header gets its own pair so
        "select all Languages" leaves Platforms / Content Types / User Categories
        untouched — instead of a single master toggle the user must then unpick.
        """
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for label, checked in (("all", True), ("none", False)):
            lnk = QLabel(f'<a href="#" style="color:{_theme.COLOR_ACCENT_BLUE};">{label}</a>')
            lnk.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            lnk.setToolTip(f"Select {label} — {title} only")
            lnk.linkActivated.connect(lambda _, c=checked: select_fn(c))
            row.addWidget(lnk)
        return w

    def _save_and_accept(self) -> None:
        # Blacklist model: save checked prefixes as excluded (checked = hidden).
        excluded_prefixes = [p for s in self._sections for p in s.checked_prefixes()]
        self._config.global_filter_excluded_categories = excluded_prefixes

        # "Hide untagged" checkbox: checked = hide = include_uncategorized False
        self._config.global_filter_include_uncategorized = not self._uncat_cb.isChecked()

        # Named content-type group exclusions
        excluded_types = [name for name, cb, _row in self._content_type_rows if cb.isChecked()]
        self._config.global_filter_excluded_content_types = excluded_types

        # Individually excluded source_category labels from the expandable Other section
        if self._content_type_other_section:
            excluded_raw = self._content_type_other_section.checked_labels()
        else:
            excluded_raw = list(getattr(self._config, "global_filter_excluded_source_categories", []))
        self._config.global_filter_excluded_source_categories = excluded_raw

        # User-defined category exclusions
        self._config.global_filter_excluded_user_categories = [
            name for name, cb, _row in self._user_category_rows if cb.isChecked()
        ]

        # Content-provenance (content_type tag) exclusions — stored as slugs.
        self._config.global_filter_excluded_tag_content_types = [
            slug for slug, cb, _row in self._content_provenance_rows if cb.isChecked()
        ]

        self._config.save()
        self.accept()
