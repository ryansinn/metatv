"""VOD Watch-Alert dialogs.

``WatchForDialog``  — small "Watch for…" input (text + type selector).
``ManageVodAlertsDialog`` — see-all + remove active watch-for rules.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

import html

from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import series_alert_identity as _series_identity
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
        self._text_edit.setClearButtonEnabled(True)
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
    """Manage every VOD watch alert: keyword watch-for rules AND monitored series.

    Opened from the always-visible "Manage" affordance in the Watch Alerts sidebar
    header.  Two grouped sections:

    - Keyword rules (top): remove a rule, or "View" its matches in the channel list
      (emits ``view_matches_requested`` and closes so the main window can populate
      the list).
    - Series — new-episode alerts (below): each monitored series with a per-series
      "Stop" button that removes it from ``monitored_series``.

    Absorbs everything the retired ``MonitoredSeriesDialog`` did.

    Remove/Stop are RECOVERABLE (mirror-not-cage), not immediate: clicking either
    flips the row to strikethrough with the button swapped for "Undo" — the row
    stays visible, its stored ``alerted_ids``/``viewed_ids`` history untouched.
    The actual config mutation (``remove_vod_watch_alert`` / ``remove_monitored_series``)
    only happens for rows STILL pending when the dialog closes (Close button, Esc,
    or the window's X — all route through ``reject()``); see
    :meth:`_finalize_pending_removals`.
    """

    # Emitted when a rule OR series is removed so the host can refresh dependent views.
    changed = pyqtSignal()
    # Emitted when the user clicks "View matches" on a rule row (text, match_type).
    view_matches_requested = pyqtSignal(str, str)

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        # Recoverable-remove: rows flipped to pending-remove (rule "created" id /
        # series_channel_id) — nothing is actually deleted from config until the
        # dialog closes with the row still pending (see _finalize_pending_removals).
        self._pending_remove_rules: set[str] = set()
        self._pending_remove_series: set[str] = set()
        self.setWindowTitle("Manage Watch Alerts")
        self.setMinimumSize(480, 420)
        self._setup_ui()
        self._load()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr = QLabel(f"{_icons.alert_icon}  Manage Watch Alerts")
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
            "You'll be alerted when matching content — or a new episode of a "
            "monitored series — appears on any of your sources."
        )
        hint.setWordWrap(True)
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

    def _sub_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        _theme.style(lbl, "DIALOG_SUBHEADER")
        return lbl

    def _muted_line(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_SM}; padding: 2px 4px;")
        return lbl

    def _load(self) -> None:
        while self._scroll_vl.count():
            item = self._scroll_vl.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        rules = self._config.get_vod_watch_alerts()
        series = self._config.get_monitored_series()
        counts = []
        if rules:
            counts.append(f"{len(rules)} rule{'s' if len(rules) != 1 else ''}")
        if series:
            counts.append(f"{len(series)} series")
        self._count_lbl.setText("  ·  ".join(counts))

        # ── Keyword rules ─────────────────────────────────────────────────
        self._scroll_vl.addWidget(self._sub_header("Movies & Series — keyword rules"))
        if rules:
            for rule in rules:
                self._scroll_vl.addWidget(self._make_row(rule))
        else:
            self._scroll_vl.addWidget(self._muted_line(
                'No keyword rules yet — click the "+" in the Watch Alerts header to add one.'
            ))

        # ── Monitored series ──────────────────────────────────────────────
        self._scroll_vl.addWidget(self._sub_header("Series — new-episode alerts"))
        if series:
            # New-episode series first, then alphabetical by cleaned title.
            series_sorted = sorted(
                series,
                key=lambda e: (
                    -(e.get("unseen_new") or 0),
                    (e.get("display_title") or e.get("title") or "").lower(),
                ),
            )
            # Dim inline disambiguator, non-empty only when two series share a
            # cleaned title (same helper the sidebar uses — one source of truth).
            suffixes = _series_identity.disambiguation_suffixes(series_sorted)
            for entry, suffix in zip(series_sorted, suffixes):
                self._scroll_vl.addWidget(self._make_series_row(entry, suffix))
        else:
            self._scroll_vl.addWidget(self._muted_line(
                'No monitored series yet — right-click a series → "Alert me to new episodes".'
            ))

        self._scroll_vl.addStretch()

    def _make_row(self, rule: dict) -> QWidget:
        rule_created = rule.get("created", "")
        text = rule.get("text") or "Unknown"
        match_type = rule.get("match_type", "any")
        alerted_count = len(rule.get("alerted_ids") or [])

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        # Recoverable remove (mirror-not-cage): a pending row collapses to just its
        # (strikethrough) name + "Undo" — nothing else is actionable until restored.
        if rule_created in self._pending_remove_rules:
            name_lbl = QLabel(f"{_icons.alert_icon} {text}")
            _theme.style(name_lbl, "DIALOG_PENDING_REMOVE_NAME")
            hl.addWidget(name_lbl, 1)

            undo_btn = QPushButton(f"{_icons.undo_icon} Undo")
            undo_btn.setFlat(True)
            _theme.style(undo_btn, "LINK_BTN_SM")
            undo_btn.setToolTip(f"Keep the watch-for rule for '{text}'")
            undo_btn.clicked.connect(
                lambda _checked=False, rc=rule_created: self._undo_rule(rc)
            )
            hl.addWidget(undo_btn)
            return row

        cursor_affordance.set_clickable(row)

        name_lbl = QLabel(f"{_icons.alert_icon} {text}")
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        hl.addWidget(name_lbl, 1)

        type_icons = {"movie": _icons.movie_icon, "series": _icons.series_icon}
        type_lbl = type_icons.get(match_type, "")
        type_display = f"{type_lbl} {match_type.capitalize()}" if type_lbl else "Any"
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

        view_btn = QPushButton(f"{_icons.search_icon} View")
        view_btn.setFlat(True)
        view_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ACCENT_BLUE};"
            f" border: none; padding: 1px 6px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        view_btn.setToolTip(f"Show all content matching '{text}' in the channel list")
        view_btn.clicked.connect(
            lambda _checked=False, t=text, mt=match_type: self._view_matches(t, mt)
        )
        hl.addWidget(view_btn)

        remove_btn = QPushButton(f"{_icons.close_icon} Remove")
        remove_btn.setFlat(True)
        _theme.style(remove_btn, "DIALOG_DANGER_LINK")
        remove_btn.setToolTip(f"Remove the watch-for rule for '{text}'")
        remove_btn.clicked.connect(
            lambda _checked=False, rc=rule_created: self._remove(rc)
        )
        hl.addWidget(remove_btn)

        return row

    def _make_series_row(self, entry: dict, suffix: str = "") -> QWidget:
        """One monitored-series row: cleaned title + unseen badge + Stop button.

        Args:
            entry: The raw monitored-series config entry.
            suffix: A dim inline disambiguator (non-empty only when this cleaned
                title collides with another monitored series).
        """
        cid = entry.get("series_channel_id", "")
        title = entry.get("display_title") or entry.get("title") or "Unknown series"
        unseen = entry.get("unseen_new") or 0

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        # Recoverable remove (mirror-not-cage): a pending row collapses to just its
        # (strikethrough) name + "Undo" — nothing else is actionable until restored.
        if cid in self._pending_remove_series:
            name_lbl = QLabel(f"{_icons.series_icon} {title}")
            _theme.style(name_lbl, "DIALOG_PENDING_REMOVE_NAME")
            hl.addWidget(name_lbl, 1)

            undo_btn = QPushButton(f"{_icons.undo_icon} Undo")
            undo_btn.setFlat(True)
            _theme.style(undo_btn, "LINK_BTN_SM")
            undo_btn.setToolTip(f"Keep monitoring {title} for new episodes")
            undo_btn.clicked.connect(
                lambda _checked=False, c=cid: self._undo_series(c)
            )
            hl.addWidget(undo_btn)
            return row

        # Always-on identity tooltip so any series is fully identifiable on hover,
        # even when two share a cleaned title.
        identity_tip = _series_identity.identity_lines(
            language=entry.get("language", ""),
            region=entry.get("region", ""),
            source=entry.get("source", ""),
        )
        row.setToolTip(f"{title}\n\n{identity_tip}")

        name_lbl = QLabel()
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        if suffix:
            # Rich text so the dim suffix flows right after the title.
            name_lbl.setTextFormat(Qt.TextFormat.RichText)
            name_lbl.setText(
                f"{html.escape(_icons.series_icon)} {html.escape(title)} "
                f'<span style="color:{_theme.COLOR_MUTED}; font-size:{_theme.FONT_SM}">'
                f"{html.escape(suffix)}</span>"
            )
        else:
            name_lbl.setText(f"{_icons.series_icon} {title}")
        hl.addWidget(name_lbl, 1)

        if unseen > 0:
            ep_word = "ep" if unseen == 1 else "eps"
            badge = QLabel(f"{_icons.new_episodes_icon} +{unseen} {ep_word}")
            badge.setStyleSheet(
                f"color: {_theme.COLOR_ACCENT_GREEN}; font-size: {_theme.FONT_SM};"
                " font-weight: bold;"
            )
            badge.setToolTip(f"{unseen} new {ep_word} since you last looked")
            hl.addWidget(badge)

        stop_btn = QPushButton(f"{_icons.close_icon} Stop")
        stop_btn.setFlat(True)
        _theme.style(stop_btn, "DIALOG_DANGER_LINK")
        stop_btn.setToolTip(f"Stop new-episode alerts for {title}")
        stop_btn.clicked.connect(lambda _checked=False, c=cid: self._stop_series(c))
        hl.addWidget(stop_btn)

        return row

    # ── Actions ──────────────────────────────────────────────────────────────

    def _view_matches(self, text: str, match_type: str) -> None:
        """Emit view_matches_requested and close so the main window can show results."""
        self.view_matches_requested.emit(text, match_type)
        self.accept()

    def _remove(self, rule_created: str) -> None:
        """Flip the rule to pending-remove (strikethrough + Undo).

        No config mutation yet — ``alerted_ids``/``viewed_ids`` history stays
        intact until :meth:`_finalize_pending_removals` runs at dialog close, so
        an Undo before then restores the rule exactly as it was.
        """
        self._pending_remove_rules.add(rule_created)
        logger.info(f"VOD watch-for rule marked pending-remove: {rule_created}")
        self._load()

    def _undo_rule(self, rule_created: str) -> None:
        """Restore a rule flipped to pending-remove."""
        self._pending_remove_rules.discard(rule_created)
        self._load()

    def _stop_series(self, series_channel_id: str) -> None:
        """Flip the series to pending-remove (strikethrough + Undo).

        No config mutation yet — see :meth:`_remove`; the same recoverable-remove
        standard applies to monitored series.
        """
        self._pending_remove_series.add(series_channel_id)
        logger.info(f"Series marked pending-remove for new-episode alerts: {series_channel_id}")
        self._load()

    def _undo_series(self, series_channel_id: str) -> None:
        """Restore a series flipped to pending-remove."""
        self._pending_remove_series.discard(series_channel_id)
        self._load()

    def _finalize_pending_removals(self) -> None:
        """Actually delete anything still flipped to pending-remove.

        Called from :meth:`reject` — the Close button, Esc, and the window's X
        button all route through ``QDialog.reject()`` (Qt's default ``closeEvent``
        delegates to it), so this is the single finalize chokepoint regardless of
        how the dialog closes.  Idempotent: clears both pending sets, so a second
        call (e.g. reject() invoked more than once) is a no-op.
        """
        changed = False
        for rule_created in self._pending_remove_rules:
            self._config.remove_vod_watch_alert(rule_created)
            logger.info(f"Removed VOD watch-for rule: {rule_created}")
            changed = True
        for series_channel_id in self._pending_remove_series:
            self._config.remove_monitored_series(series_channel_id)
            logger.info(f"Stopped new-episode alerts for series {series_channel_id}")
            changed = True
        self._pending_remove_rules.clear()
        self._pending_remove_series.clear()
        if changed:
            self.changed.emit()

    def reject(self) -> None:
        """Esc / Close button / window X — finalize any still-pending removals first."""
        self._finalize_pending_removals()
        super().reject()
