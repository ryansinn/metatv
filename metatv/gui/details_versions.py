"""Version chips and category-name types for the details pane."""
import re as _re
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QPushButton, QLabel,
    QLayout, QLayoutItem, QMenu, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QPoint

from loguru import logger

from metatv.core.channel_name_utils import normalize_region_code, REGION_FULL_NAMES

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

_CHANNEL_PREFIX_RE = _re.compile(r'^([A-Z][A-Z0-9\-]{1,11})\s*([★|])\s*(.+)$')


def resolve_category_name(prefix: str, config=None) -> str:
    """Return the human-readable name for a prefix code, checking user overrides first."""
    if config is not None:
        overrides = getattr(config, "category_name_overrides", {})
        if prefix in overrides:
            return overrides[prefix]
    code = normalize_region_code(prefix)
    return REGION_FULL_NAMES.get(code, REGION_FULL_NAMES.get(prefix, ""))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ChannelVersion:
    """A single alternative version of the currently displayed channel."""
    channel_id: str
    name: str
    in_queue: bool
    detected_prefix: str | None = None
    is_preferred: bool = False
    is_filtered: bool = False
    is_hidden: bool = False
    is_hidden_category: bool = False
    is_favorite: bool = False
    in_history: bool = False
    provider_name: str | None = None


# ---------------------------------------------------------------------------
# _FlowLayout
# ---------------------------------------------------------------------------

class _FlowLayout(QLayout):
    """Wrapping flow layout — arranges widgets left-to-right, wrapping to new rows."""

    def __init__(self, parent=None, h_spacing: int = 4, v_spacing: int = 4):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = eff.x(), eff.y(), 0
        for item in self._items:
            w = item.widget()
            if w and not w.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > eff.right() and row_h > 0:
                x = eff.x()
                y += row_h + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                row_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# _CategoryNamePopup
# ---------------------------------------------------------------------------

class _CategoryNamePopup(QFrame):
    """Inline popup for naming/renaming a category prefix."""

    name_saved = pyqtSignal(str, str)   # prefix, new_name

    def __init__(self, prefix: str, current_name: str, config, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(
            "QFrame { background: #252525; border: 1px solid #555; border-radius: 4px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        prefix_lbl = QLabel(prefix)
        prefix_lbl.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        layout.addWidget(prefix_lbl)
        self._edit = QLineEdit(current_name)
        self._edit.setPlaceholderText(f"Name for {prefix}…")
        self._edit.setMinimumWidth(160)
        self._edit.returnPressed.connect(self._on_save)
        layout.addWidget(self._edit)
        save_btn = QPushButton(config.watched_icon)
        save_btn.setFixedSize(28, 28)
        save_btn.setToolTip("Save category name")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)
        self._prefix = prefix
        self._edit.setFocus()

    def _on_save(self) -> None:
        self.name_saved.emit(self._prefix, self._edit.text().strip())
        self.close()


# ---------------------------------------------------------------------------
# _VersionSection
# ---------------------------------------------------------------------------

class _VersionSection(QWidget):
    """Preferred-version nudge banner + wrapping category chip row."""

    version_selected         = pyqtSignal(str)        # channel_id
    favorite_toggled         = pyqtSignal(str)        # channel_id
    queue_toggled            = pyqtSignal(str)        # channel_id
    hide_requested           = pyqtSignal(str)        # channel_id
    prefix_block_requested   = pyqtSignal(str)        # prefix
    prefix_unblock_requested = pyqtSignal(str)        # prefix
    prefix_name_saved        = pyqtSignal(str, str)   # prefix, name
    manage_filters_requested = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Preferred version nudge banner (green)
        self._pref_nudge = QFrame()
        self._pref_nudge.setStyleSheet(
            "QFrame { background: rgba(80,160,80,0.15); border-radius: 4px;"
            " border: 1px solid rgba(80,160,80,0.4); }"
        )
        nudge_row = QHBoxLayout(self._pref_nudge)
        nudge_row.setContentsMargins(8, 4, 8, 4)
        self._pref_nudge_lbl = QLabel()
        self._pref_nudge_lbl.setStyleSheet("font-size: 11px; color: #8fca8f;")
        self._pref_nudge_lbl.setWordWrap(True)
        self._pref_nudge_switch_btn = QPushButton("Switch")
        self._pref_nudge_switch_btn.setFlat(True)
        self._pref_nudge_switch_btn.setStyleSheet(
            "color: #8fca8f; font-size: 11px; font-weight: bold; border: none;"
        )
        self._pref_nudge_switch_btn.setToolTip("Switch the details pane to show your preferred version")
        nudge_row.addWidget(self._pref_nudge_lbl, 1)
        nudge_row.addWidget(self._pref_nudge_switch_btn)
        self._pref_nudge.hide()
        layout.addWidget(self._pref_nudge)

        # Chip row: "Categories: [chip] [chip] …"
        self._row_container = QWidget()
        row_layout = QHBoxLayout(self._row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        cat_label = QLabel("Categories:")
        cat_label.setStyleSheet("color: #888; font-size: 11px;")
        cat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        row_layout.addWidget(cat_label, 0)

        self._chips_row = QWidget()
        from PyQt6.QtWidgets import QSizePolicy
        self._chips_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._chips_layout = _FlowLayout(self._chips_row, h_spacing=4, v_spacing=4)
        row_layout.addWidget(self._chips_row, 1)

        self._row_container.hide()
        layout.addWidget(self._row_container)

    def load(self, versions: list[ChannelVersion]) -> None:
        """Rebuild the chip row from a fresh version list."""
        layout = self._chips_layout
        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        try:
            self._pref_nudge_switch_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._pref_nudge.hide()
        self._row_container.hide()

        if not versions:
            return

        active   = [v for v in versions if not v.is_filtered and not v.is_hidden]
        filtered = [v for v in versions if v.is_filtered and not v.is_hidden]

        if not active and not filtered:
            return

        preferred = next((v for v in versions if v.is_preferred), None)
        if preferred:
            self._pref_nudge_lbl.setText(
                f"{self.config.preferred_version_icon} Preferred: {preferred.name}"
            )
            self._pref_nudge_switch_btn.clicked.connect(
                lambda: self.version_selected.emit(preferred.channel_id)
            )
            self._pref_nudge.show()

        for v in active:
            layout.addWidget(self._make_active_chip(v))
        for v in filtered:
            layout.addWidget(self._make_greyed_chip(v))

        self._row_container.show()
        self._chips_row.updateGeometry()

    def clear(self) -> None:
        self.load([])

    # ------------------------------------------------------------------ #
    # Chip factories                                                       #
    # ------------------------------------------------------------------ #

    def _make_active_chip(self, v: ChannelVersion) -> QPushButton:
        prefix = v.detected_prefix or "?"
        status = ""
        if v.is_preferred: status += f" {self.config.preferred_version_icon}"
        if v.in_queue:     status += f" {self.config.queue_icon}"
        if v.is_favorite:  status += f" {self.config.favorite_icon}"
        if v.in_history:   status += f" {self.config.history_icon}"

        chip = QPushButton(prefix + status)
        chip.setStyleSheet(
            "QPushButton { font-size: 11px; color: #ccc; border: 1px solid #555;"
            " border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #fff; border-color: #888;"
            " background: rgba(255,255,255,0.05); }"
        )
        full = resolve_category_name(prefix, self.config)
        tip = full or prefix
        if v.provider_name:
            tip += f"\nSource: {v.provider_name}"
        chip.setToolTip(tip)
        chip.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, _v=v, _c=chip: self._show_version_chip_menu(_c.mapToGlobal(pos), _v)
        )
        return chip

    def _make_greyed_chip(self, v: ChannelVersion) -> QPushButton:
        prefix = v.detected_prefix or "?"
        is_hidden_cat = v.is_hidden_category
        extra = "text-decoration: line-through;" if is_hidden_cat else ""
        chip = QPushButton(prefix)
        chip.setStyleSheet(
            f"QPushButton {{ font-size: 11px; color: #444; border: 1px solid #333;"
            f" border-radius: 4px; padding: 2px 8px; {extra} }}"
        )
        full = resolve_category_name(prefix, self.config)
        reason = "hidden" if is_hidden_cat else "filtered"
        chip.setToolTip(f"{full or prefix} ({prefix}) — {reason}. Right-click to manage.")
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, p=prefix, hid=is_hidden_cat, _c=chip:
                self._show_filtered_chip_menu(_c.mapToGlobal(pos), p, hid)
        )
        return chip

    # ------------------------------------------------------------------ #
    # Context menus                                                        #
    # ------------------------------------------------------------------ #

    def _show_version_chip_menu(self, global_pos, v: ChannelVersion) -> None:
        prefix = v.detected_prefix or "?"
        full = resolve_category_name(prefix, self.config)
        header = f"{full} ({prefix})" if full else prefix

        menu = QMenu(self)
        title_act = menu.addAction(header)
        title_act.setEnabled(False)
        menu.addSeparator()

        show_act = menu.addAction(f"Show details for {prefix} version")
        show_act.setToolTip(v.name)
        menu.addSeparator()

        fav_act   = menu.addAction("Remove from Favorites" if v.is_favorite else "Add to Favorites")
        queue_act = menu.addAction("Remove from Queue" if v.in_queue else "Add to Queue")
        hide_act  = menu.addAction(f"Hide this {prefix} version")
        hide_act.setToolTip(f"Hides only: {v.name}")
        menu.addSeparator()

        filter_act   = menu.addAction(f'Filter out ALL "{prefix}" content')
        filter_act.setToolTip(f"Deselects {prefix} from Content Categories — easy to undo from filter panel")
        hide_cat_act = menu.addAction(f"Hide the {prefix} category")
        hide_cat_act.setToolTip(f"Suppresses {prefix} entirely — removed from filter options")
        menu.addSeparator()

        edit_act = menu.addAction("Edit Category Name…")

        chosen = menu.exec(global_pos)
        if chosen == show_act:
            self.version_selected.emit(v.channel_id)
        elif chosen == fav_act:
            self.favorite_toggled.emit(v.channel_id)
        elif chosen == queue_act:
            self.queue_toggled.emit(v.channel_id)
        elif chosen == hide_act:
            self.hide_requested.emit(v.channel_id)
        elif chosen in (filter_act, hide_cat_act):
            self.prefix_block_requested.emit(prefix)
        elif chosen == edit_act:
            self._show_category_name_popup(prefix, global_pos)

    def _show_filtered_chip_menu(self, global_pos, prefix: str, is_hidden: bool) -> None:
        full = resolve_category_name(prefix, self.config)
        state = "hidden" if is_hidden else "filtered"
        header = f"{full} ({prefix}) — {state}" if full else f"{prefix} — {state}"

        menu = QMenu(self)
        title_act = menu.addAction(header)
        title_act.setEnabled(False)
        menu.addSeparator()

        restore_act = menu.addAction(
            f"Unhide {prefix} category" if is_hidden else f"Remove filter on {prefix} content"
        )
        menu.addSeparator()
        manage_act = menu.addAction("Manage content filters…")

        chosen = menu.exec(global_pos)
        if chosen == restore_act:
            self.prefix_unblock_requested.emit(prefix)
        elif chosen == manage_act:
            self.manage_filters_requested.emit()

    def _show_category_name_popup(self, prefix: str, pos) -> None:
        current = resolve_category_name(prefix, self.config)
        popup = _CategoryNamePopup(prefix, current, self.config, self)
        popup.name_saved.connect(lambda p, n: self.prefix_name_saved.emit(p, n))
        popup.move(pos)
        popup.show()
