"""Category picker dialog — assign channels to a user-defined category.

Workflow:
  1. Type to filter existing categories or create a new one.
  2. Select a mood on the 5-point gradient bar (neutral by default).
  3. Optionally add the category to Global Exclusions (auto-suggested for Dislike).
  4. Confirm — channels are bulk-assigned and the Discover shelf is queued for refresh.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database


# ── Mood constants ─────────────────────────────────────────────────────────────

MOOD_NONE         = None
MOOD_LIKE         = "like"
MOOD_CURIOUS      = "curious"
MOOD_NOT_FOR_ME   = "not_interested"
MOOD_DISLIKE      = "dislike"

_MOOD_ORDER = [MOOD_LIKE, MOOD_CURIOUS, MOOD_NONE, MOOD_NOT_FOR_ME, MOOD_DISLIKE]

_MOOD_COLORS = {
    MOOD_LIKE:       ("#2ecc71", "#1a7a43"),   # bright green bg, dark text
    MOOD_CURIOUS:    ("#27ae60", "#155a2e"),   # forest green
    MOOD_NONE:       ("#555555", "#cccccc"),   # mid grey
    MOOD_NOT_FOR_ME: ("#c0392b", "#f5a5a0"),   # brick red
    MOOD_DISLIKE:    ("#e74c3c", "#ffffff"),   # bright red
}

_MOOD_SELECTED_STYLE = (
    "QPushButton {{ background: {bg}; color: {fg}; border: 2px solid {bg};"
    " border-radius: 14px; padding: 4px 10px; font-size: 14px; font-weight: bold; }}"
)
_MOOD_IDLE_STYLE = (
    "QPushButton { background: #2a2a2a; color: #666; border: 1px solid #444;"
    " border-radius: 14px; padding: 4px 10px; font-size: 14px; }"
    "QPushButton:hover { background: #333; color: #aaa; border-color: #666; }"
)


class _MoodBar(QWidget):
    """5-point gradient mood selector: Like · Curious · Neutral · Not for me · Dislike."""

    mood_changed = pyqtSignal(object)   # emits mood string or None

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._current: str | None = MOOD_NONE
        self._buttons: dict[str | None, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        specs: list[tuple[str | None, str]] = [
            (MOOD_LIKE,       config.like_icon),
            (MOOD_CURIOUS,    config.curious_icon),
            (MOOD_NONE,       "—"),
            (MOOD_NOT_FOR_ME, config.not_interested_icon),
            (MOOD_DISLIKE,    config.dislike_icon),
        ]
        for mood, icon in specs:
            btn = QPushButton(icon)
            btn.setFixedSize(36, 28)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, m=mood: self._select(m))
            self._buttons[mood] = btn
            layout.addWidget(btn)

        layout.addStretch()
        self._set_tooltips()
        self._refresh_styles()

    def _set_tooltips(self) -> None:
        tips = {
            MOOD_LIKE:       "Like — recommend more content like this",
            MOOD_CURIOUS:    "Exploring — show me more to help me decide",
            MOOD_NONE:       "Neutral — no recommendation effect (default)",
            MOOD_NOT_FOR_ME: "Not for me — deprioritize in recommendations",
            MOOD_DISLIKE:    "Dislike — negative weight; suggests Global Exclusion",
        }
        for mood, tip in tips.items():
            if mood in self._buttons:
                self._buttons[mood].setToolTip(tip)

    def _select(self, mood: str | None) -> None:
        self._current = mood
        self._refresh_styles()
        self.mood_changed.emit(mood)

    def _refresh_styles(self) -> None:
        for mood, btn in self._buttons.items():
            if mood == self._current:
                bg, fg = _MOOD_COLORS[mood]
                btn.setStyleSheet(
                    _MOOD_SELECTED_STYLE.format(bg=bg, fg=fg)
                )
                btn.setChecked(True)
            else:
                btn.setStyleSheet(_MOOD_IDLE_STYLE)
                btn.setChecked(False)

    def current_mood(self) -> str | None:
        return self._current

    def set_mood(self, mood: str | None) -> None:
        self._current = mood
        self._refresh_styles()


# ── Main dialog ────────────────────────────────────────────────────────────────

_CREATE_PREFIX = "➕ Create “"   # ➕ Create "
_CREATE_SUFFIX = "”"                  # "


class CategoryPickerDialog(QDialog):
    """Pick or create a user category and assign mood + optional global exclusion."""

    def __init__(
        self,
        db: Database,
        config: Config,
        channel_count: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._channel_count = channel_count
        self._categories: list[dict] = []   # [{name, count, mood}]
        self._selected_category: str = ""
        self._is_new: bool = False

        self.setWindowTitle("Add to Category")
        self.setMinimumWidth(380)
        self._setup_ui()
        self._load_categories()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        n = self._channel_count
        header = QLabel(
            f"Adding <b>{n:,} channel{'s' if n != 1 else ''}</b> to category:"
        )
        header.setStyleSheet("font-size: 12px;")
        vl.addWidget(header)

        # ── Quick-pick shortcuts ───────────────────────────────────────────────
        quick_row = QHBoxLayout()
        quick_lbl = QLabel("Quick:")
        quick_lbl.setStyleSheet("color: #666; font-size: 11px;")
        quick_row.addWidget(quick_lbl)

        _quick_picks = [
            ("🗑 Trash",       "Trash",       MOOD_DISLIKE,    True,  "#5a1a1a", "#ff8888"),
            ("👀 Watch Later", "Watch Later", MOOD_NONE,       False, "#1a3a5a", "#88aaff"),
            ("❓ Explore",     "Explore",     MOOD_CURIOUS,    False, "#1a3a1a", "#88cc88"),
        ]
        for label, name, mood, exclude, bg, fg in _quick_picks:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {fg}44;"
                f" border-radius: 10px; padding: 3px 10px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {bg}cc; }}"
            )
            _tips = {
                "Trash":       "Trash — Dislike mood + Global Exclusions (hide everywhere)",
                "Watch Later": "Watch Later — Neutral mood, no recommendation effect",
                "Explore":     "Explore — Curious mood, surfaces more like this",
            }
            btn.setToolTip(_tips.get(name, f'Create or use "{name}" category'))
            btn.clicked.connect(
                lambda _, n=name, m=mood, ex=exclude: self._apply_quick_pick(n, m, ex)
            )
            quick_row.addWidget(btn)
        quick_row.addStretch()
        vl.addLayout(quick_row)

        # ── Search / type box ──────────────────────────────────────────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search or type new category name…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_text_changed)
        vl.addWidget(self._search)

        # ── Category list ──────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setMaximumHeight(220)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(lambda _: self._try_accept())
        vl.addWidget(self._list)

        # ── Mood bar ───────────────────────────────────────────────────────────
        mood_hdr = QLabel("Mood  (optional):")
        mood_hdr.setStyleSheet("color: #888; font-size: 11px;")
        vl.addWidget(mood_hdr)

        self._mood_bar = _MoodBar(self._config)
        self._mood_bar.mood_changed.connect(self._on_mood_changed)
        vl.addWidget(self._mood_bar)

        # ── Global Exclusions toggle (shown when Dislike selected or new category) ──
        self._excl_cb = QCheckBox("Add this category to Global Exclusions (hide everywhere)")
        self._excl_cb.setStyleSheet("font-size: 11px; color: #aaa;")
        self._excl_cb.setToolTip(
            "Channels in this category will be hidden from Discovery,\n"
            "Recommendations, and the channel list everywhere.\n"
            "You can still find them by searching or in the Exclusions dialog."
        )
        self._excl_cb.setVisible(False)
        vl.addWidget(self._excl_cb)

        # ── Buttons ────────────────────────────────────────────────────────────
        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Add to Category")
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._btn_box.accepted.connect(self._try_accept)
        self._btn_box.rejected.connect(self.reject)
        vl.addWidget(self._btn_box)

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_categories(self) -> None:
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            self._categories = repos.channels.get_all_user_categories()
        finally:
            session.close()
        self._rebuild_list("")

    def _rebuild_list(self, query: str) -> None:
        self._list.clear()
        q = query.strip().lower()

        # User-created categories (sorted by count desc — already that order)
        user_cats = self._categories
        matched_user = [c for c in user_cats if not q or q in c["name"].lower()]

        if matched_user:
            sep = QListWidgetItem("— Your categories —")
            sep.setFlags(Qt.ItemFlag.NoItemFlags)
            sep.setForeground(self._list.palette().color(
                self._list.palette().ColorRole.PlaceholderText
            ))
            self._list.addItem(sep)

        for cat in matched_user:
            mood_icon = self._mood_icon(cat["mood"])
            label = f"{mood_icon} {cat['name']}  ({cat['count']:,})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cat["name"])
            item.setData(Qt.ItemDataRole.UserRole + 1, False)  # not new
            self._list.addItem(item)

        # "Create" option — only when typed text doesn't exactly match an existing name
        existing_names = {c["name"].lower() for c in user_cats}
        if query.strip() and query.strip().lower() not in existing_names:
            create_item = QListWidgetItem(
                f"{_CREATE_PREFIX}{query.strip()}{_CREATE_SUFFIX}"
            )
            create_item.setData(Qt.ItemDataRole.UserRole, query.strip())
            create_item.setData(Qt.ItemDataRole.UserRole + 1, True)   # is new
            create_item.setForeground(self._list.palette().color(
                self._list.palette().ColorRole.Highlight
            ))
            self._list.addItem(create_item)

        # Auto-select the first real item if only one match
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.flags() & Qt.ItemFlag.ItemIsSelectable:
                if not q or (item.data(Qt.ItemDataRole.UserRole) or "").lower().startswith(q):
                    self._list.setCurrentItem(item)
                    self._on_item_clicked(item)
                    break

    # ── Interaction ────────────────────────────────────────────────────────────

    def _mood_icon(self, mood: str | None) -> str:
        icons = {
            MOOD_LIKE:       self._config.like_icon,
            MOOD_CURIOUS:    self._config.curious_icon,
            MOOD_NOT_FOR_ME: self._config.not_interested_icon,
            MOOD_DISLIKE:    self._config.dislike_icon,
        }
        return icons.get(mood, "·")

    def _on_text_changed(self, text: str) -> None:
        self._rebuild_list(text)
        # If text exactly matches an existing category, select it
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and (item.data(Qt.ItemDataRole.UserRole) or "").lower() == text.strip().lower():
                self._list.setCurrentItem(item)
                self._on_item_clicked(item)
                return

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        name = item.data(Qt.ItemDataRole.UserRole) or ""
        is_new = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        self._selected_category = name
        self._is_new = is_new

        # Pre-fill mood from existing category
        if not is_new:
            cat = next((c for c in self._categories if c["name"] == name), None)
            if cat:
                self._mood_bar.set_mood(cat["mood"])

        # Show/update exclusions checkbox
        self._update_excl_visibility()
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(name))

    def _on_mood_changed(self, mood: str | None) -> None:
        self._update_excl_visibility()
        # Auto-suggest exclusion when Dislike is selected
        if mood == MOOD_DISLIKE and not self._excl_cb.isChecked():
            self._excl_cb.setChecked(True)
        elif mood != MOOD_DISLIKE:
            # Un-suggest but don't force uncheck (user may have set it manually)
            pass

    def _update_excl_visibility(self) -> None:
        # Show exclusion checkbox when creating a new category OR when mood=Dislike
        mood = self._mood_bar.current_mood()
        show = self._is_new or mood == MOOD_DISLIKE
        self._excl_cb.setVisible(show)

        # Update label to include category name
        name = self._selected_category
        if name:
            self._excl_cb.setText(
                f"Add “{name}” to Global Exclusions (hide everywhere)"
            )

    def _apply_quick_pick(self, name: str, mood: str | None, exclude: bool) -> None:
        """Pre-fill name, mood, and exclusion from a quick-pick shortcut."""
        self._search.setText(name)       # fires _on_text_changed → auto-selects list item
        self._mood_bar.set_mood(mood)    # override (set_mood doesn't emit mood_changed)
        self._update_excl_visibility()
        if mood == MOOD_DISLIKE or exclude:
            self._excl_cb.setChecked(True)

    def _try_accept(self) -> None:
        if self._selected_category:
            self.accept()

    # ── Public result accessors ────────────────────────────────────────────────

    def selected_category(self) -> str:
        return self._selected_category

    def selected_mood(self) -> str | None:
        return self._mood_bar.current_mood()

    def add_to_exclusions(self) -> bool:
        return self._excl_cb.isVisible() and self._excl_cb.isChecked()
