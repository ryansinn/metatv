"""Categories management dialog.

Shows all user-defined categories with their channels.  Each section is
collapsible; every channel row has Remove (clears the assignment) and
Change Category (reassigns via CategoryPickerDialog) actions.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.gui import theme as _theme


class _CategorySection(QWidget):
    """Collapsible section for one user category."""

    changed = pyqtSignal()

    def __init__(
        self,
        cat_info: dict,
        excluded_cats: set[str],
        db: Database,
        config: Config,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._name: str = cat_info["name"]
        self._mood: str | None = cat_info.get("mood")
        self._count: int = cat_info["count"]
        self._is_excluded: bool = self._name in excluded_cats
        self._expanded = False
        self._channels_loaded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(
            f"QWidget {{ background: {_theme.COLOR_BG_CARD}; border-radius: 4px; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(6)

        self._expand_btn = QPushButton(config.expand_icon)
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.setFlat(True)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_btn.setToolTip("Expand / collapse")
        self._expand_btn.clicked.connect(self._toggle)
        hl.addWidget(self._expand_btn)

        mood_icon = self._mood_icon()
        name_lbl = QLabel(f"{mood_icon}  {self._name}")
        name_lbl.setStyleSheet(f"font-weight: bold; font-size: {_theme.FONT_LG};")
        hl.addWidget(name_lbl)

        count_lbl = QLabel(f"({self._count:,})")
        count_lbl.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_MD};")
        hl.addWidget(count_lbl)

        if self._is_excluded:
            badge = QLabel("globally excluded")
            badge.setStyleSheet(
                f"color: {_theme.COLOR_ERR_2}; font-size: {_theme.FONT_SM}; padding: 2px 6px;"
                f" background: {_theme.OVERLAY_ERR2_15}; border-radius: 3px;"
            )
            badge.setToolTip(
                "Channels in this category are hidden everywhere.\n"
                "Open Global Exclusions to change this."
            )
            hl.addWidget(badge)

        hl.addStretch()
        outer.addWidget(hdr)

        # ── Body (lazy-loaded, hidden by default) ──────────────────────────────
        self._body = QWidget()
        self._body.setVisible(False)
        self._body_vl = QVBoxLayout(self._body)
        self._body_vl.setContentsMargins(28, 4, 0, 4)
        self._body_vl.setSpacing(2)
        outer.addWidget(self._body)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _mood_icon(self) -> str:
        return {
            "like":         self._config.like_icon,
            "curious":      self._config.curious_icon,
            "not_interested": self._config.not_interested_icon,
            "dislike":      self._config.dislike_icon,
        }.get(self._mood or "", "·")

    # ── Expand / collapse ──────────────────────────────────────────────────────

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._expand_btn.setText(
            self._config.collapse_icon if self._expanded else self._config.expand_icon
        )
        self._body.setVisible(self._expanded)
        if self._expanded and not self._channels_loaded:
            self._load_channels()

    def _load_channels(self) -> None:
        self._channels_loaded = True
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            channels = repos.channels.get_by_user_category(self._name)
        finally:
            session.close()

        if not channels:
            lbl = QLabel("No channels in this category.")
            lbl.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_MD}; padding: 4px 0;")
            self._body_vl.addWidget(lbl)
            return

        for ch in channels:
            self._body_vl.addWidget(self._make_row(ch))

    def _make_row(self, channel) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 1, 0, 1)
        hl.setSpacing(6)

        name_lbl = QLabel(channel.name)
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_LOW};")
        hl.addWidget(name_lbl, 1)

        move_btn = QPushButton("Change Category")
        move_btn.setFlat(True)
        move_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        move_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ACCENT_BLUE}; padding: 1px 6px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        move_btn.setToolTip("Move this channel to a different category")
        move_btn.clicked.connect(lambda _, cid=channel.id: self._change_category(cid))
        hl.addWidget(move_btn)

        remove_btn = QPushButton(f"{self._config.close_icon} Remove")
        remove_btn.setFlat(True)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ERR_2}; padding: 1px 6px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_RED_BRIGHT}; }}"
        )
        remove_btn.setToolTip(
            "Remove from this category — channel returns to normal visibility"
        )
        remove_btn.clicked.connect(lambda _, cid=channel.id: self._remove(cid))
        hl.addWidget(remove_btn)

        return row

    # ── Actions ────────────────────────────────────────────────────────────────

    def _remove(self, channel_id: str) -> None:
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.remove_user_category([channel_id])
        finally:
            session.close()
        logger.info(f"Removed channel {channel_id} from category {self._name!r}")
        self.changed.emit()

    def _change_category(self, channel_id: str) -> None:
        from metatv.gui.category_picker_dialog import CategoryPickerDialog
        from metatv.core.repositories import RepositoryFactory
        dlg = CategoryPickerDialog(self._db, self._config, 1, self)
        if dlg.exec() != CategoryPickerDialog.DialogCode.Accepted:
            return
        category = dlg.selected_category()
        mood     = dlg.selected_mood()
        exclude  = dlg.add_to_exclusions()
        if not category:
            return
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.assign_user_category([channel_id], category, mood)
        finally:
            session.close()
        if exclude and category not in self._config.global_filter_excluded_user_categories:
            self._config.global_filter_excluded_user_categories.append(category)
            self._config.save()
        logger.info(f"Moved channel {channel_id} to category {category!r}")
        self.changed.emit()


class CategoriesDialog(QDialog):
    """Browse and manage all user-defined channel categories."""

    def __init__(self, db: Database, config: Config, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self.setWindowTitle("Manage Categories")
        self.setMinimumSize(620, 500)
        self._setup_ui()
        self._load()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr = QLabel("Your Categories")
        hdr.setStyleSheet(f"font-size: {_theme.FONT_XL}; font-weight: bold;")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        hint = QLabel("Expand a category to see its channels and manage assignments.")
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_MD};")
        hdr_row.addWidget(hint)
        vl.addLayout(hdr_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        vl.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_content = QWidget()
        self._scroll_vl = QVBoxLayout(self._scroll_content)
        self._scroll_vl.setSpacing(6)
        self._scroll_area.setWidget(self._scroll_content)
        vl.addWidget(self._scroll_area)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        # Clear existing sections
        while self._scroll_vl.count():
            item = self._scroll_vl.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            cats = repos.channels.get_all_user_categories()
        finally:
            session.close()

        excluded = set(getattr(self._config, "global_filter_excluded_user_categories", []))

        if not cats:
            empty = QLabel(
                "No categories yet.\n\n"
                "Select channels in the channel list, right-click, and choose a quick category\n"
                'or "Add to Category..." to get started.'
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_LG}; padding: 30px;")
            self._scroll_vl.addWidget(empty)
        else:
            for cat in cats:
                section = _CategorySection(cat, excluded, self._db, self._config, self)
                section.changed.connect(self._load)
                self._scroll_vl.addWidget(section)

        self._scroll_vl.addStretch()
