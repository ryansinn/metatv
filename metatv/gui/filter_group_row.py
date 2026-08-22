"""Private filter-panel widgets — _TriCheckbox, _ItemRow, _GroupRow, _Section.

These are implementation details of FilterPanel; import FilterPanel from
metatv.gui.filter_panel, not these classes directly.

Top-N cap for large sections
─────────────────────────────
When a flat section has more than ``_SHOW_ALL_THRESHOLD`` items (default 40),
``set_flat_items`` renders only the top ``_SHOW_ALL_TOP_N`` rows (default 30)
and appends a "Show all (N) ⋯" button.  Activating the button reveals all
remaining rows and changes the button to "Show less".  Collapsing again
restores the capped view.

The cap is display-only: every item is tracked in ``self._rows``, so
``get_selected_keys``, ``get_all_keys``, ``restore_selection`` etc. always
cover the full set.  The overflow rows are simply hidden, not deleted.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)

from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


# ── Accent colours per section (values are theme tokens) ────────────────────────
def _accent_colors() -> dict[str, str]:
    return {
        "media":    _theme.COLOR_ACCENT_BLUE,
        "language": _theme.COLOR_ACCENT_BLUE,
        "subtitle": _theme.COLOR_FACET_SUBTITLE,
        "dub":      _theme.COLOR_FACET_DUB,
        "format":   _theme.COLOR_FACET_FORMAT,
        "region":   _theme.COLOR_ACCENT_GREEN,
        "platform": _theme.COLOR_ACCENT_PURPLE,
        "quality":  _theme.COLOR_ACCENT_ORANGE,
        "category": _theme.COLOR_ACCENT_ORANGE,   # warm orange — live-channel kind
        "genre":    _theme.COLOR_ACCENT_TEAL,
        "untagged": _theme.COLOR_MUTED_2,
    }

# Top-N cap configuration — display-only, no values are dropped.
# Sections with more than _SHOW_ALL_THRESHOLD items render only _SHOW_ALL_TOP_N
# rows; the rest are hidden behind a "Show all (N)" expander button.
_SHOW_ALL_THRESHOLD: int = 40
_SHOW_ALL_TOP_N:     int = 30


def _fmt(n: int) -> str:
    return f"{n:,}" if n >= 1000 else str(n)


# ── Tri-state header checkbox ──────────────────────────────────────────────────

class _TriCheckbox(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTristate(True)
        _theme.style(self, "FILTER_CHECKBOX")

    def refresh_theme(self) -> None:
        """Re-apply the current theme's :data:`theme.FILTER_CHECKBOX` role."""
        _theme.style(self, "FILTER_CHECKBOX")

    def mousePressEvent(self, event):
        state = self.checkState()
        if state == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)
        self.stateChanged.emit(self.checkState().value)


# ── Single item row ────────────────────────────────────────────────────────────

#: Key of the per-section "Untagged" footer toggle. Not a facet VALUE — it is
#: the switch for "and everything this facet cannot describe", so it is kept
#: out of every value-set API on _Section (see set_untagged_row).
UNTAGGED_KEY = "__untagged__"


class _ItemRow(QWidget):
    toggled = pyqtSignal(str, bool)
    right_clicked = pyqtSignal(str, QPoint)   # key, global position
    only_clicked = pyqtSignal(str)            # key — user wants panel-wide "Only this"

    def __init__(self, key: str, label: str, count: int,
                 indent: int = 0, parent=None):
        super().__init__(parent)
        self._key = key
        cursor_affordance.set_clickable(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 + indent, 2, 8, 2)
        layout.setSpacing(6)

        self._cb = QCheckBox()
        self._cb.setChecked(True)
        _theme.style(self._cb, "FILTER_CHECKBOX")
        layout.addWidget(self._cb)

        self._label = QLabel(label)
        self._label.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT};")
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setMinimumWidth(0)   # prevent RTL/long text from forcing the panel wider
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._count_lbl: QLabel | None = None
        if count > 0:
            self._count_lbl = QLabel(_fmt(count))
            _theme.style(self._count_lbl, "ITEM_COUNT")
            self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(self._count_lbl)

        # "Only" link-button — shows only this item across all facet sections
        self._only_btn = QPushButton(_icons.filter_only_icon)
        self._only_btn.setFixedSize(16, 16)
        _theme.style(self._only_btn, "FILTER_ONLY_BTN")
        self._only_btn.setToolTip("Show only this group")
        self._only_btn.clicked.connect(lambda: self.only_clicked.emit(self._key))
        layout.addWidget(self._only_btn)

        self._cb.stateChanged.connect(
            lambda state: self.toggled.emit(self._key,
                                            state == Qt.CheckState.Checked.value)
        )

    def refresh_theme(self) -> None:
        """Re-apply this row's tokens (checkbox, label, count, "Only" button)."""
        _theme.style(self._cb, "FILTER_CHECKBOX")
        self._label.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT};")
        if self._count_lbl is not None:
            _theme.style(self._count_lbl, "ITEM_COUNT")
        _theme.style(self._only_btn, "FILTER_ONLY_BTN")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._cb.toggle()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        self.right_clicked.emit(self._key, event.globalPos())
        event.accept()

    def is_checked(self) -> bool:
        return self._cb.isChecked()

    def set_checked(self, checked: bool, block: bool = True):
        if block:
            self._cb.blockSignals(True)
        self._cb.setChecked(checked)
        if block:
            self._cb.blockSignals(False)

    def key(self) -> str:
        return self._key


# ── Expandable group row (Region hierarchy) ────────────────────────────────────

class _GroupRow(QWidget):
    changed = pyqtSignal()
    child_right_clicked = pyqtSignal(str, QPoint)   # item key, global position
    only_clicked = pyqtSignal(str)                  # group_name — panel-wide "Only this group"

    def __init__(self, group_name: str, total_count: int,
                 child_items: list[tuple[str, str, int]],
                 indent: int = 0, *, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._group_name = group_name
        self._children: list[_ItemRow] = []
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8 + indent, 3, 8, 3)
        hl.setSpacing(4)

        self._expand_btn = QPushButton(config.expand_icon)
        self._expand_btn.setFixedSize(16, 16)
        self._expand_btn.setFlat(True)
        self._expand_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_XS}; }}")
        self._expand_btn.setToolTip("Show the codes in this group")
        self._expand_btn.clicked.connect(self._toggle_expand)
        hl.addWidget(self._expand_btn)

        self._tri = _TriCheckbox()
        self._tri.setCheckState(Qt.CheckState.Checked)
        self._tri.stateChanged.connect(self._on_tri_changed)
        hl.addWidget(self._tri)

        self._name_lbl = QLabel(group_name)
        self._name_lbl.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT_LOW};")
        self._name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Preferred)
        hl.addWidget(self._name_lbl)

        self._count_lbl: QLabel | None = None
        if total_count > 0:
            self._count_lbl = QLabel(_fmt(total_count))
            _theme.style(self._count_lbl, "ITEM_COUNT")
            self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(self._count_lbl)

        # "Only" link-button — shows only this group's channels across all facet sections
        self._only_btn = QPushButton(_icons.filter_only_icon)
        self._only_btn.setFixedSize(16, 16)
        _theme.style(self._only_btn, "FILTER_ONLY_BTN")
        self._only_btn.setToolTip("Show only this group")
        self._only_btn.clicked.connect(lambda: self.only_clicked.emit(self._group_name))
        hl.addWidget(self._only_btn)

        outer.addWidget(header)

        self._child_container = QWidget()
        cl = QVBoxLayout(self._child_container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        for key, label, count in child_items:
            row = _ItemRow(key, label, count, indent=indent + 16)
            row.toggled.connect(self._on_child_toggled)
            row.right_clicked.connect(self.child_right_clicked)
            cl.addWidget(row)
            self._children.append(row)

        self._child_container.hide()
        outer.addWidget(self._child_container)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._child_container.setVisible(self._expanded)
        glyph = self._config.collapse_icon if self._expanded else self._config.expand_icon
        self._expand_btn.setText(glyph)
        self._expand_btn.setToolTip(
            "Hide the codes in this group" if self._expanded
            else "Show the codes in this group"
        )

    def _on_tri_changed(self, state_val: int):
        state = Qt.CheckState(state_val)
        if state == Qt.CheckState.PartiallyChecked:
            return
        checked = (state == Qt.CheckState.Checked)
        for row in self._children:
            row.set_checked(checked)
        self.changed.emit()

    def _on_child_toggled(self, key: str, checked: bool):
        self._update_tri()
        self.changed.emit()

    def _update_tri(self):
        states = [r.is_checked() for r in self._children]
        self._tri.blockSignals(True)
        if all(states):
            self._tri.setCheckState(Qt.CheckState.Checked)
        elif any(states):
            self._tri.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._tri.setCheckState(Qt.CheckState.Unchecked)
        self._tri.blockSignals(False)

    def get_selected_keys(self) -> list[str]:
        return [r.key() for r in self._children if r.is_checked()]

    def set_all_checked(self, checked: bool):
        self._tri.blockSignals(True)
        self._tri.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._tri.blockSignals(False)
        for row in self._children:
            row.set_checked(checked)

    def is_all_checked(self) -> bool:
        return all(r.is_checked() for r in self._children)

    def restore_selection(self, selected_keys: set[str]):
        for row in self._children:
            row.set_checked(row.key() in selected_keys)
        self._update_tri()

    def refresh_theme(self) -> None:
        """Re-apply this group's tokens (expand button, tri-checkbox, name,
        count, "Only" button) and recurse into every child :class:`_ItemRow`.
        """
        self._expand_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_XS}; }}")
        self._tri.refresh_theme()
        self._name_lbl.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT_LOW};")
        if self._count_lbl is not None:
            _theme.style(self._count_lbl, "ITEM_COUNT")
        _theme.style(self._only_btn, "FILTER_ONLY_BTN")
        for row in self._children:
            row.refresh_theme()


# ── Section widget ─────────────────────────────────────────────────────────────

class _Section(QWidget):
    changed = pyqtSignal()
    collapse_toggled = pyqtSignal()                     # collapse/expand only — does NOT mean filter changed
    item_right_clicked = pyqtSignal(str, str, QPoint)   # item_key, section_key, global_pos
    item_only_requested = pyqtSignal(str, str)          # item_key, section_key — "Only" button/action

    def __init__(self, section_key: str, title: str,
                 and_axis: bool = False,
                 initially_expanded: bool = False,
                 info_text: str = "",
                 info_icon: str = "ℹ",
                 *,
                 config,
                 parent=None):
        super().__init__(parent)
        self._key = section_key
        self._config = config
        self._rows: list[_ItemRow] = []
        self._groups: list[_GroupRow] = []
        self._expanded = initially_expanded

        # Show-all expander state — only used when the section is capped.
        # _overflow_rows tracks rows hidden behind the expander button.
        # _show_all_btn is the QPushButton inserted after the top-N rows.
        self._overflow_rows: list[_ItemRow] = []
        self._show_all_btn: QPushButton | None = None
        self._show_all_expanded: bool = False

        # "Untagged" footer — created lazily by set_untagged_row(); see there
        # for why it is kept out of _rows.
        self._untagged_row: _ItemRow | None = None
        self._untagged_sep: QFrame | None = None

        self._and_axis = and_axis
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header — full row is clickable to expand/collapse
        self._header = QWidget()
        self._header.setObjectName("sectionHeader")
        self._header.setFixedHeight(30)
        cursor_affordance.set_clickable(self._header)
        self._header.mousePressEvent = lambda _e: self._toggle_collapse()
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(4)

        _init_glyph = config.collapse_icon if initially_expanded else config.expand_icon
        self._collapse_btn = QPushButton(_init_glyph)
        self._collapse_btn.setFixedSize(16, 16)
        self._collapse_btn.setFlat(True)
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        hl.addWidget(self._collapse_btn)

        self._title_lbl = QLabel(title.upper())
        hl.addWidget(self._title_lbl)

        self._narrows_lbl: QLabel | None = None
        if and_axis:
            self._narrows_lbl = QLabel("— filter")
            hl.addWidget(self._narrows_lbl)

        self._info_btn: QPushButton | None = None
        if info_text:
            self._info_btn = QPushButton(info_icon)
            self._info_btn.setFixedSize(16, 16)
            self._info_btn.setFlat(True)
            self._info_btn.setToolTip(info_text)
            # Also show on click for touch / keyboard users
            self._info_btn.clicked.connect(
                lambda _checked=False, btn=self._info_btn, txt=info_text:
                    QToolTip.showText(
                        btn.mapToGlobal(btn.rect().center()), txt, btn
                    )
            )
            hl.addWidget(self._info_btn)

        hl.addStretch()

        self._summary_lbl = QLabel("")
        hl.addWidget(self._summary_lbl)

        self._select_all = _TriCheckbox()
        self._select_all.setCheckState(Qt.CheckState.Checked)
        self._select_all.setToolTip("Select all / deselect all")
        self._select_all.stateChanged.connect(self._on_select_all)
        hl.addWidget(self._select_all)

        outer.addWidget(self._header)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(self._sep)

        self.refresh_theme()

        # Content
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 2, 0, 4)
        self._content_layout.setSpacing(0)
        self._content.setVisible(initially_expanded)
        outer.addWidget(self._content)

    # ── public ─────────────────────────────────────────────────────────────

    def section_key(self) -> str:
        return self._key

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._content.setVisible(expanded)
        glyph = self._config.collapse_icon if expanded else self._config.expand_icon
        self._collapse_btn.setText(glyph)

    def refresh_theme(self) -> None:
        """Re-apply this section's tokens (header, collapse/info buttons, title,
        separator) and recurse into every row/group currently populated.

        Safe to call from ``__init__`` before any rows exist (``self._rows``/
        ``self._groups`` start empty) — used there to avoid duplicating the
        style computation between construction and a live theme switch.
        """
        accent = _accent_colors().get(self._key, _theme.COLOR_ACCENT_BLUE)
        self._header.setStyleSheet(
            f"QWidget#sectionHeader {{ background: {_theme.COLOR_BG_SECTION}; "
            f"border-left: 3px solid {accent}; }}"
        )
        self._collapse_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_XS};"
            " background: transparent; }")
        self._title_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_MD}; font-weight: bold; color: {_theme.COLOR_TEXT}; "
            "letter-spacing: 1px;")
        if self._narrows_lbl is not None:
            self._narrows_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ACCENT_ORANGE_FADED};"
                " font-style: italic;")
        if self._info_btn is not None:
            self._info_btn.setStyleSheet(
                f"QPushButton {{ color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_SM};"
                " background: transparent; }"
                f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_3}; }}"
            )
        self._summary_lbl.setStyleSheet(f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED_2};")
        self._select_all.refresh_theme()
        self._sep.setStyleSheet(f"color: {_theme.COLOR_LINE_DARK};")
        if self._show_all_btn is not None:
            _theme.style(self._show_all_btn, "FILTER_SHOW_ALL_BTN")
        for row in self._rows:
            row.refresh_theme()
        for group in self._groups:
            group.refresh_theme()
        if self._untagged_row is not None:
            self._untagged_row.refresh_theme()
            self._refresh_untagged_theme()

    def set_flat_items(self, items: list[tuple[str, str, int]]):
        """Populate the section with a sorted flat list of (key, label, count) tuples.

        When ``len(items) > _SHOW_ALL_THRESHOLD``, only the first
        ``_SHOW_ALL_TOP_N`` rows are shown initially; a "Show all (N) ⋯"
        button is appended that reveals the remaining rows on click.  Small
        sections (≤ threshold) are rendered without any cap.

        The cap is display-only — all items are tracked in ``self._rows`` so
        that ``get_selected_keys``, ``get_all_keys``, ``restore_selection``,
        etc. always cover the full set.
        """
        self._clear()
        total = len(items)
        needs_cap = total > _SHOW_ALL_THRESHOLD

        for idx, (key, label, count) in enumerate(items):
            row = _ItemRow(key, label, count)
            row.toggled.connect(self._on_item_toggled)
            row.right_clicked.connect(
                lambda k, pos, sk=self._key: self.item_right_clicked.emit(k, sk, pos)
            )
            row.only_clicked.connect(
                lambda k, sk=self._key: self.item_only_requested.emit(k, sk)
            )
            self._content_layout.addWidget(row)
            self._rows.append(row)

            if needs_cap and idx >= _SHOW_ALL_TOP_N:
                # Overflow: hidden until the user expands
                row.hide()
                self._overflow_rows.append(row)

        if needs_cap:
            overflow_count = total - _SHOW_ALL_TOP_N
            self._show_all_btn = QPushButton(
                f"{_icons.show_all_icon} Show all ({total})"
            )
            _theme.style(self._show_all_btn, "FILTER_SHOW_ALL_BTN")
            self._show_all_btn.setToolTip(
                f"Show all {total} values — {overflow_count} more below the top {_SHOW_ALL_TOP_N}"
            )
            self._show_all_btn.clicked.connect(self._toggle_show_all)
            self._content_layout.addWidget(self._show_all_btn)
            self._show_all_expanded = False

        self._update_ui()

    def set_grouped_items(self,
                          groups: list[tuple[str, int, list[tuple[str, str, int]]]]):
        self._clear()
        for group_name, total, children in groups:
            g = _GroupRow(group_name, total, children, config=self._config)
            g.changed.connect(self._on_group_changed)
            g.child_right_clicked.connect(
                lambda k, pos, sk=self._key: self.item_right_clicked.emit(k, sk, pos)
            )
            g.only_clicked.connect(
                lambda k, sk=self._key: self.item_only_requested.emit(k, sk)
            )
            self._content_layout.addWidget(g)
            self._groups.append(g)
        self._update_ui()

    # ── "Untagged" footer row ────────────────────────────────────────────────
    #
    # Deliberately NOT a member of ``_rows``. It is not a VALUE of the facet —
    # it is the answer to "and what about everything this facet can't describe?"
    # Keeping it out of _rows means it is never capped by the Show-all limit,
    # never reordered by count, and never counted by ``is_all_selected`` /
    # ``get_selected_keys`` / ``get_all_keys``, so ticking every value still
    # reads as "no constraint" exactly as before.

    def set_untagged_row(self, count: int, checked: bool = True) -> None:
        """Show "Untagged — N" beneath the values, always visible.

        *count* is how many channels carry NO tag of this facet at all, within
        the same visibility scope as the value counts. It is a property of the
        DATA, not of the current selection, so it does not move as boxes are
        ticked — that is the whole point: it is the number that explains why
        unticking a value did not change the result count as much as expected.
        """
        if self._untagged_row is not None:
            self._untagged_row.deleteLater()
            self._untagged_sep.deleteLater()

        # A plain 1px filled rect, NOT setFrameShape(HLine): a framed QFrame
        # draws its line from the PALETTE, so a stylesheet "color:" on it paints
        # nothing at all — which is exactly what the first version did.
        self._untagged_sep = QFrame()
        self._untagged_sep.setFixedHeight(1)

        self._untagged_row = _ItemRow(UNTAGGED_KEY, "Untagged", count)
        self._untagged_row.setToolTip(
            "Titles with no value on this facet at all.\n\n"
            "Checked (default): they are shown — a filter for a fact the app "
            "never learned about a title should not hide it.\n"
            "Unchecked: only titles that carry one of the values above."
        )
        self._untagged_row.set_checked(checked)
        self._untagged_row.toggled.connect(lambda _k, _v: self.changed.emit())
        # No "Only" button: it means "show only this VALUE across every section",
        # and there is no such value here. Leaving it would put a pointing-hand
        # cursor over a click that silently does nothing — the same dead
        # affordance the sub/dub chips were fixed for.
        self._untagged_row._only_btn.hide()

        # Appended AFTER the value rows every time. ``set_flat_items`` clears and
        # rebuilds the body, so the footer has to be (re)attached last or it ends
        # up above the values it is a footer for.
        self._content_layout.addWidget(self._untagged_sep)
        self._content_layout.addWidget(self._untagged_row)

        visible = count > 0
        self._untagged_row.setVisible(visible)
        self._untagged_sep.setVisible(visible)
        self._refresh_untagged_theme()

    def untagged_included(self) -> bool:
        """True when untagged content passes this facet (the default)."""
        return self._untagged_row is None or self._untagged_row.is_checked()

    def has_untagged_row(self) -> bool:
        return self._untagged_row is not None

    def _refresh_untagged_theme(self) -> None:
        if self._untagged_sep is not None:
            # COLOR_BORDER, not COLOR_LINE_DARK: this hairline is doing real
            # work — it is the boundary between "values of this facet" and "and
            # everything it can't describe". At the darker token it rendered
            # invisibly and the row read as one more value.
            _theme.style_fn(
                self._untagged_sep,
                lambda: f"QFrame {{ background-color: {_theme.COLOR_BORDER}; }}",
            )

    def get_selected_keys(self) -> list[str]:
        keys = [r.key() for r in self._rows if r.is_checked()]
        for grp in self._groups:
            keys.extend(grp.get_selected_keys())
        return keys

    def get_all_keys(self) -> list[str]:
        """Return every key in this section regardless of check state."""
        keys = [r.key() for r in self._rows]
        for grp in self._groups:
            keys.extend(c.key() for c in grp._children)
        return keys

    def is_all_selected(self) -> bool:
        if self._rows:
            return all(r.is_checked() for r in self._rows)
        return all(g.is_all_checked() for g in self._groups) if self._groups else True

    def select_all(self):
        self._select_all.blockSignals(True)
        self._select_all.setCheckState(Qt.CheckState.Checked)
        self._select_all.blockSignals(False)
        for r in self._rows:
            r.set_checked(True)
        for g in self._groups:
            g.set_all_checked(True)
        if self._untagged_row is not None:
            self._untagged_row.set_checked(True)   # "show everything" includes the undescribed
        self._update_summary()

    def select_none(self):
        self._select_all.blockSignals(True)
        self._select_all.setCheckState(Qt.CheckState.Unchecked)
        self._select_all.blockSignals(False)
        for r in self._rows:
            r.set_checked(False)
        for g in self._groups:
            g.set_all_checked(False)
        if self._untagged_row is not None:
            self._untagged_row.set_checked(False)  # "start from nothing" means nothing
        self._update_summary()

    def restore_selection(self, selected_keys: set[str]):
        for r in self._rows:
            r.set_checked(r.key() in selected_keys)
        for g in self._groups:
            g.restore_selection(selected_keys)
        self._update_ui()

    def check_only(self, key: str):
        """Check only the item with this key; uncheck all others in the section."""
        for r in self._rows:
            r.set_checked(r.key() == key)
        for g in self._groups:
            for child in g._children:
                child.set_checked(child.key() == key)
            g._update_tri()
        self._update_ui()
        self.changed.emit()

    def select_only_group(self, key: str) -> None:
        """Select all children of the group named *key*; uncheck everything else.

        Used by the panel-level "Only" action for grouped (hierarchical) sections
        like Region. For flat sections, ``key`` matches an item directly and this
        behaves identically to ``check_only(key)``.

        Does NOT emit ``changed`` — the panel emits ``filter_changed`` once after
        calling this across all sections.
        """
        group_names = {g._group_name for g in self._groups}
        if key in group_names:
            # Key is a group header: check all its children, uncheck all others
            for g in self._groups:
                is_target = (g._group_name == key)
                for child in g._children:
                    child.set_checked(is_target)
                g._update_tri()
        else:
            # Key is a flat item (or a child code inside a group)
            for r in self._rows:
                r.set_checked(r.key() == key)
            for g in self._groups:
                for child in g._children:
                    child.set_checked(child.key() == key)
                g._update_tri()
        self._update_ui()

    # ── private ────────────────────────────────────────────────────────────

    def _clear(self):
        for w in self._rows + self._groups:
            w.deleteLater()
        self._rows.clear()
        self._groups.clear()
        self._overflow_rows.clear()
        if self._show_all_btn is not None:
            self._show_all_btn.deleteLater()
            self._show_all_btn = None
        self._show_all_expanded = False

    def _toggle_collapse(self):
        self.set_expanded(not self._expanded)
        self.collapse_toggled.emit()  # save collapse state without triggering a filter reload

    def _toggle_show_all(self) -> None:
        """Show or hide the overflow rows when the 'Show all' button is clicked."""
        self._show_all_expanded = not self._show_all_expanded
        for row in self._overflow_rows:
            row.setVisible(self._show_all_expanded)
        if self._show_all_btn is not None:
            total = len(self._rows)
            if self._show_all_expanded:
                self._show_all_btn.setText(f"{_icons.collapse_icon} Show less")
                self._show_all_btn.setToolTip(f"Collapse back to top {_SHOW_ALL_TOP_N}")
            else:
                self._show_all_btn.setText(f"{_icons.show_all_icon} Show all ({total})")
                self._show_all_btn.setToolTip(
                    f"Show all {total} values — "
                    f"{total - _SHOW_ALL_TOP_N} more below the top {_SHOW_ALL_TOP_N}"
                )

    def _on_select_all(self, state_val: int):
        state = Qt.CheckState(state_val)
        if state == Qt.CheckState.PartiallyChecked:
            return
        checked = (state == Qt.CheckState.Checked)
        for r in self._rows:
            r.set_checked(checked)
        for g in self._groups:
            g.set_all_checked(checked)
        self._update_ui()
        self.changed.emit()

    def _on_item_toggled(self, key: str, checked: bool):
        self._update_ui()
        self.changed.emit()

    def _on_group_changed(self):
        self._update_ui()
        self.changed.emit()

    def _update_ui(self):
        self._update_select_all_state()
        self._update_summary()

    def _update_select_all_state(self):
        self._select_all.blockSignals(True)
        if self.is_all_selected():
            self._select_all.setCheckState(Qt.CheckState.Checked)
        elif self.get_selected_keys():
            self._select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._select_all.setCheckState(Qt.CheckState.Unchecked)
        self._select_all.blockSignals(False)

    def _update_summary(self):
        """Show active selections in header when collapsed."""
        sel = self.get_selected_keys()
        total = len(self._rows) + sum(len(g._children) for g in self._groups)
        if not sel or len(sel) == total:
            self._summary_lbl.setText("")
        elif len(sel) <= 3:
            self._summary_lbl.setText(", ".join(sel[:3]))
        else:
            self._summary_lbl.setText(f"{len(sel)}/{total}")
