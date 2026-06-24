"""Dev-only floating QA Testing Checklist window.

Gated by ``METATV_DEV`` environment variable — never constructed or shown
when the gate is closed.  Normal users see zero impact.

The window reads ``test_steps`` from every ``WhatsNewEntry`` in
``metatv.whats_new.WHATS_NEW``, filtering to entries that:
  - have at least one step, AND
  - have ``id > config.qa_verified_id`` (not yet purged).

Entries are displayed newest-first.  Each entry shows a header with the
title, date, and a progress fraction ("2/3"), plus one ``QCheckBox`` per
step.  Checked state is persisted in ``config.qa_checked_steps`` (a dict
mapping ``str(entry_id)`` → list of checked step indices).

When every visible entry is fully checked the window switches to an
"all clear" empty state and enables a **Purge** button that advances the
``qa_verified_id`` cursor past all current entries so the list resets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.whats_new import WhatsNewEntry


class QAChecklistWindow(QWidget):
    """Floating, always-on-top dev QA checklist window.

    Args:
        config: App config instance (read/write for persistence).
        entries: Full ``WHATS_NEW`` list; filtered inside ``__init__``.
        parent: Parent widget (MainWindow); child destruction is automatic.
    """

    def __init__(
        self,
        config: Config,
        entries: list[WhatsNewEntry],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._config = config
        self._all_entries = entries  # full list; re-filter on each refresh
        self._checkboxes: dict[int, list[QCheckBox]] = {}  # entry_id → checkboxes

        self.setWindowTitle("Testing Checklist")
        self.setMinimumWidth(420)
        self.setMinimumHeight(200)
        self.resize(460, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── header bar ────────────────────────────────────────────────────────
        header_bar = QWidget()
        header_bar.setStyleSheet(
            f"background: {_theme.COLOR_BG_BAR};"
            f" border-bottom: 1px solid {_theme.COLOR_LINE};"
        )
        hbar_layout = QHBoxLayout(header_bar)
        hbar_layout.setContentsMargins(12, 8, 12, 8)

        icon_label = QLabel(_icons.qa_checklist_icon)
        icon_label.setStyleSheet(f"font-size: {_theme.FONT_2XL};")
        hbar_layout.addWidget(icon_label)

        title_label = QLabel("Testing Checklist")
        title_label.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; font-weight: bold;"
            f" color: {_theme.COLOR_TEXT};"
        )
        hbar_layout.addWidget(title_label, stretch=1)

        self._purge_btn = QPushButton(f"{_icons.qa_purge_icon}  Mark all done")
        self._purge_btn.setToolTip(
            "Clear all checked items — advances the verified cursor so these"
            " entries no longer appear."
        )
        self._purge_btn.setEnabled(False)
        self._purge_btn.setStyleSheet(_theme.PANEL_BTN)
        self._purge_btn.clicked.connect(self._on_purge)
        hbar_layout.addWidget(self._purge_btn)

        root.addWidget(header_bar)

        # ── scrollable body ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 12, 12, 12)
        self._body_layout.setSpacing(0)

        scroll.setWidget(self._body)
        root.addWidget(scroll, stretch=1)

        self._refresh()

    # ── public ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read config and redraw the checklist (e.g. after a purge)."""
        self._refresh()

    # ── private helpers ───────────────────────────────────────────────────────

    def _open_entries(self) -> list[WhatsNewEntry]:
        """Return entries with test_steps that haven't been purged yet, newest first."""
        verified = self._config.qa_verified_id
        return sorted(
            (e for e in self._all_entries if e.test_steps and e.id > verified),
            key=lambda e: e.id,
            reverse=True,
        )

    def _is_entry_complete(self, entry: WhatsNewEntry) -> bool:
        """Return True when every step of *entry* is checked in config."""
        checked = set(self._config.qa_checked_steps.get(str(entry.id), []))
        return len(checked) >= len(entry.test_steps) and all(
            i in checked for i in range(len(entry.test_steps))
        )

    def _all_complete(self, open_entries: list[WhatsNewEntry]) -> bool:
        """Return True when every open entry is fully checked."""
        return bool(open_entries) and all(
            self._is_entry_complete(e) for e in open_entries
        )

    def _clear_body(self) -> None:
        """Remove all widgets from the body layout."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

    def _refresh(self) -> None:
        """Rebuild the body from current config state."""
        self._clear_body()
        open_entries = self._open_entries()

        if not open_entries:
            self._render_empty_state()
            self._purge_btn.setEnabled(False)
            return

        for entry in open_entries:
            self._render_entry(entry)
            # Separator between entries
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
            self._body_layout.addWidget(sep)

        # Push content to top
        self._body_layout.addStretch(1)

        all_done = self._all_complete(open_entries)
        self._purge_btn.setEnabled(all_done)

    def _render_empty_state(self) -> None:
        """Show a friendly 'nothing to test' message."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 40, 0, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(_icons.qa_all_clear_icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: {_theme.FONT_4XL};")
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel("Nothing to test")
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_XL}; color: {_theme.COLOR_MUTED}; padding: 8px 0 4px 0;"
        )
        layout.addWidget(msg_lbl)

        sub_lbl = QLabel("All test steps are complete or no entries have steps yet.")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};")
        layout.addWidget(sub_lbl)

        self._body_layout.addWidget(container)

    def _render_entry(self, entry: WhatsNewEntry) -> None:
        """Render one entry block: header + checkboxes."""
        checked_indices = set(self._config.qa_checked_steps.get(str(entry.id), []))
        n_total = len(entry.test_steps)
        n_checked = sum(1 for i in range(n_total) if i in checked_indices)
        is_complete = n_checked >= n_total

        # ── entry header ──────────────────────────────────────────────────────
        header_widget = QWidget()
        header_widget.setContentsMargins(0, 0, 0, 0)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 10, 0, 6)
        header_layout.setSpacing(6)

        title_color = _theme.COLOR_MUTED if is_complete else _theme.COLOR_TEXT
        title_lbl = QLabel(entry.title)
        title_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; font-weight: bold; color: {title_color};"
        )
        header_layout.addWidget(title_lbl, stretch=1)

        date_lbl = QLabel(entry.date)
        date_lbl.setStyleSheet(f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED_2};")
        header_layout.addWidget(date_lbl)

        progress_color = _theme.COLOR_OK if is_complete else _theme.COLOR_DIM
        progress_lbl = QLabel(f"{n_checked}/{n_total}")
        progress_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; color: {progress_color};"
            f" font-weight: bold; padding-left: 4px;"
        )
        header_layout.addWidget(progress_lbl)

        self._body_layout.addWidget(header_widget)

        # ── step checkboxes ───────────────────────────────────────────────────
        # QCheckBox.setWordWrap() is not available in PyQt6; instead we use a
        # plain QCheckBox (no text) paired with a word-wrapped QLabel in a row.
        checkboxes: list[QCheckBox] = []
        for idx, step in enumerate(entry.test_steps):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)

            cb = QCheckBox()
            cb.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            step_color = _theme.COLOR_MUTED if idx in checked_indices else _theme.COLOR_TEXT_LOW
            cb.setStyleSheet(
                f"QCheckBox {{ padding: 0; spacing: 0; }}"
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            )

            step_lbl = QLabel(step)
            step_lbl.setWordWrap(True)
            step_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {step_color};"
            )
            step_lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

            row_layout.addWidget(cb, alignment=Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(step_lbl, stretch=1)

            # ── set initial checked state (block signals during restore) ──────
            cb.blockSignals(True)
            cb.setChecked(idx in checked_indices)
            cb.blockSignals(False)

            checkboxes.append(cb)
            self._body_layout.addWidget(row)

        # Wire handlers AFTER all widgets are set
        for idx, cb in enumerate(checkboxes):
            # Capture idx and entry by value via default args
            cb.toggled.connect(
                lambda checked, eid=entry.id, step_idx=idx: self._on_step_toggled(
                    eid, step_idx, checked
                )
            )

        self._checkboxes[entry.id] = checkboxes

        # Spacing after entry's steps
        spacer = QWidget()
        spacer.setFixedHeight(6)
        self._body_layout.addWidget(spacer)

    def _on_step_toggled(self, entry_id: int, step_idx: int, checked: bool) -> None:
        """Persist checkbox state change and update progress + purge button."""
        key = str(entry_id)
        current = list(self._config.qa_checked_steps.get(key, []))

        if checked and step_idx not in current:
            current.append(step_idx)
        elif not checked and step_idx in current:
            current.remove(step_idx)

        # Build updated dict (Pydantic model — must assign a new object to trigger save)
        updated = dict(self._config.qa_checked_steps)
        updated[key] = current
        self._config.qa_checked_steps = updated
        self._config.save()
        logger.debug("QA step {}/{} → {}", entry_id, step_idx, checked)

        # Redraw the full checklist to update step colors, progress fractions,
        # and the purge button state.  The body is small (dev tool), so this is
        # the simplest correct approach.
        self._refresh()

    def _on_purge(self) -> None:
        """Advance qa_verified_id past all current entries and reset the view."""
        open_entries = self._open_entries()
        if not open_entries:
            return

        max_id = max(e.id for e in open_entries)
        self._config.qa_verified_id = max_id
        self._config.save()
        logger.info("QA checklist purged up to entry id={}", max_id)

        self._refresh()
