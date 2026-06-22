"""VOD Watch-Alert dialogs.

``WatchForDialog``  — small "Watch for…" input (text + type selector).
``ManageVodAlertsDialog`` — see-all + remove active watch-for rules.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class WatchForDialog(QDialog):
    """Small dialog to add a new VOD watch-for rule.

    The user enters a keyword / title fragment and selects whether to watch
    for a Movie, Series, or Any content type.
    """

    # Emitted when the user clicks "Watch" — carries the new rule dict.
    rule_added = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Watch for…")
        self.setMinimumWidth(380)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        hdr = QLabel(f"{_icons.alert_icon}  Watch for new content")
        hdr.setStyleSheet(f"font-size: {_theme.FONT_XL}; font-weight: bold;")
        vl.addWidget(hdr)

        hint = QLabel(
            "Get an alert when content matching this keyword appears on any of your sources."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM};")
        vl.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        vl.addWidget(sep)

        # --- Keyword input ---
        lbl_kw = QLabel("Title / keyword:")
        lbl_kw.setStyleSheet(f"font-size: {_theme.FONT_MD};")
        vl.addWidget(lbl_kw)

        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText("e.g.  Dune,  Breaking Bad,  Severance")
        self._text_edit.setStyleSheet(
            f"font-size: {_theme.FONT_MD}; padding: 4px 6px;"
        )
        vl.addWidget(self._text_edit)

        # --- Type selector ---
        type_row = QHBoxLayout()
        lbl_type = QLabel("Content type:")
        lbl_type.setStyleSheet(f"font-size: {_theme.FONT_MD};")
        type_row.addWidget(lbl_type)

        self._type_combo = QComboBox()
        self._type_combo.addItem("Any", "any")
        self._type_combo.addItem(f"{_icons.movie_icon}  Movie", "movie")
        self._type_combo.addItem(f"{_icons.series_icon}  Series", "series")
        self._type_combo.setStyleSheet(f"font-size: {_theme.FONT_MD};")
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        vl.addLayout(type_row)

        # --- Buttons ---
        buttons = QDialogButtonBox()
        self._watch_btn = QPushButton(f"{_icons.alert_icon}  Watch")
        self._watch_btn.setDefault(True)
        self._watch_btn.setStyleSheet(
            f"QPushButton {{ background: {_theme.COLOR_ACCENT}; color: {_theme.COLOR_TEXT};"
            f" border: none; border-radius: 4px; padding: 4px 14px;"
            f" font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ background: {_theme.COLOR_ACCENT_HOVER}; }}"
        )
        self._watch_btn.clicked.connect(self._on_watch)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFlat(True)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._watch_btn)
        vl.addLayout(btn_row)

        self._text_edit.returnPressed.connect(self._on_watch)
        self._text_edit.textChanged.connect(self._update_watch_btn)
        self._update_watch_btn()

    def _update_watch_btn(self) -> None:
        self._watch_btn.setEnabled(bool(self._text_edit.text().strip()))

    def _on_watch(self) -> None:
        text = self._text_edit.text().strip()
        if not text:
            return
        match_type = self._type_combo.currentData()
        rule = {
            "text": text,
            "match_type": match_type,
            "created": datetime.now(timezone.utc).isoformat(),
            "alerted_ids": [],
        }
        self.rule_added.emit(rule)
        self.accept()


class ManageVodAlertsDialog(QDialog):
    """List every active VOD watch-for rule with a remove button.

    Opening is triggered from the "Watch for…" sub-section of the Alerts sidebar.
    """

    # Emitted when a rule is removed so the host can refresh dependent views.
    changed = pyqtSignal()

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Watch-For Rules")
        self.setMinimumSize(480, 380)
        self._setup_ui()
        self._load()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr = QLabel(f"{_icons.alert_icon}  VOD Watch-For Rules")
        hdr.setStyleSheet(f"font-size: {_theme.FONT_XL}; font-weight: bold;")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_MD};"
        )
        hdr_row.addWidget(self._count_lbl)
        vl.addLayout(hdr_row)

        hint = QLabel(
            "You'll be alerted when matching content appears on any of your sources."
        )
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM};")
        vl.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        vl.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_content = QWidget()
        self._scroll_vl = QVBoxLayout(self._scroll_content)
        self._scroll_vl.setSpacing(4)
        self._scroll_area.setWidget(self._scroll_content)
        vl.addWidget(self._scroll_area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    # ── Data loading ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        while self._scroll_vl.count():
            item = self._scroll_vl.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        rules = self._config.get_vod_watch_alerts()
        self._count_lbl.setText(f"{len(rules)} active" if rules else "")

        if not rules:
            empty = QLabel(
                "No watch-for rules yet.\n\n"
                'Click the "+" in the Alerts section header to add one.'
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_LG}; padding: 30px;"
            )
            self._scroll_vl.addWidget(empty)
            self._scroll_vl.addStretch()
            return

        for rule in rules:
            self._scroll_vl.addWidget(self._make_row(rule))
        self._scroll_vl.addStretch()

    def _make_row(self, rule: dict) -> QWidget:
        rule_created = rule.get("created", "")
        text = rule.get("text") or "Unknown"
        match_type = rule.get("match_type", "any")
        alerted_count = len(rule.get("alerted_ids") or [])

        type_icons = {"movie": _icons.movie_icon, "series": _icons.series_icon}
        type_lbl = type_icons.get(match_type, "")
        type_display = f"{type_lbl} {match_type.capitalize()}" if type_lbl else "Any"

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        name_lbl = QLabel(f"{_icons.alert_icon} {text}")
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        hl.addWidget(name_lbl, 1)

        type_badge = QLabel(type_display)
        type_badge.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM};"
        )
        hl.addWidget(type_badge)

        if alerted_count > 0:
            match_badge = QLabel(f"{alerted_count} match{'es' if alerted_count != 1 else ''}")
            match_badge.setStyleSheet(
                f"color: {_theme.COLOR_ACCENT_GREEN}; font-size: {_theme.FONT_SM};"
                " font-weight: bold;"
            )
            match_badge.setToolTip(
                f"{alerted_count} channel(s) already alerted for this rule"
            )
            hl.addWidget(match_badge)

        remove_btn = QPushButton(f"{_icons.close_icon} Remove")
        remove_btn.setFlat(True)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ERR_2};"
            f" padding: 1px 6px; border: none; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_RED_BRIGHT}; }}"
        )
        remove_btn.setToolTip(f"Remove the watch-for rule for '{text}'")
        remove_btn.clicked.connect(
            lambda _checked=False, rc=rule_created: self._remove(rc)
        )
        hl.addWidget(remove_btn)

        return row

    # ── Actions ──────────────────────────────────────────────────────────────

    def _remove(self, rule_created: str) -> None:
        self._config.remove_vod_watch_alert(rule_created)
        logger.info(f"Removed VOD watch-for rule: {rule_created}")
        self._load()
        self.changed.emit()
