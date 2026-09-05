"""Record for a time window — *Catch, Keep, Record* Feature 3 Option B.

Needs no guide data at all: the user picks a start/end directly, which is
what makes recording work on a source with no EPG (settled 2026-08-30, "All
three — A, B and C" — B is the one that works on the owner's live source).
Sibling of ``schedule_recording_from_programme`` (REC-3, which schedules a
GUIDE row's own window): this is the guide-free path to the same
``RecordingManager.schedule()`` chokepoint, reached through
``MainWindow.record_channel_window`` -> ``_schedule_and_announce``
(``main_window_downloads.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from metatv.core.epg_utils import to_utc_naive
from metatv.gui import theme as _theme


def _round_up_to_5_minutes(dt: datetime) -> datetime:
    """Ceil *dt* to the next 5-minute mark (seconds/microseconds dropped).

    An already-exact 5-minute mark (e.g. 14:05:00.000000) is left unchanged —
    this is a ceiling, not "always advance by some amount".
    """
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % 5
    if remainder == 0:
        return dt
    return dt + timedelta(minutes=5 - remainder)


class RecordWindowDialog(QDialog):
    """Pick a start/end window to record a live channel — no guide needed.

    Args:
        channel_name: The channel being recorded; shown in the window title.
        provider_name: The channel's source; named in the one-connection note.
        config: Supplies ``recording_pad_start_seconds``/``_end_seconds`` as
            the padding spins' prefilled defaults (Settings ▸ Recording) —
            the same round-trip formula ``SettingsDialog`` uses.
        parent: Qt parent widget.
        now: Local wall-clock "now" the default window and validity are
            computed from. Threaded through rather than read from the real
            clock inside, so a test can freeze it; defaults to
            ``datetime.now()``.
    """

    def __init__(self, channel_name: str, provider_name: str, config,
                 parent=None, *, now: "datetime | None" = None) -> None:
        super().__init__(parent)
        self._config = config
        self._now = now if now is not None else datetime.now()
        self.setWindowTitle(f"Record {channel_name} for a time window")
        self.setMinimumWidth(400)
        self._setup_ui(provider_name)

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self, provider_name: str) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        default_start = _round_up_to_5_minutes(self._now)
        default_end = default_start + timedelta(hours=2)

        self._start_edit = QDateTimeEdit(QDateTime(default_start))
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._start_edit.setToolTip(
            "When the recording starts, in your local time.")
        self._start_edit.dateTimeChanged.connect(self._update_state)
        form.addRow("Start:", self._start_edit)

        self._end_edit = QDateTimeEdit(QDateTime(default_end))
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._end_edit.setToolTip(
            "When the recording stops, in your local time.")
        self._end_edit.dateTimeChanged.connect(self._update_state)
        form.addRow("End:", self._end_edit)

        # Minutes on screen, seconds in config — same formula as
        # SettingsDialog._load_values/_save_values, so the two never disagree.
        pad_start_default = int(round(
            getattr(self._config, "recording_pad_start_seconds", 0) / 60))
        self._pad_start_spin = QSpinBox()
        self._pad_start_spin.setRange(-120, 120)
        self._pad_start_spin.setSuffix(" min")
        self._pad_start_spin.setValue(pad_start_default)
        self._pad_start_spin.setToolTip(
            "Signed offset on the start, minutes — prefilled from Settings "
            "▸ Recording. Negative starts earlier."
        )
        form.addRow("Start padding:", self._pad_start_spin)

        pad_end_default = int(round(
            getattr(self._config, "recording_pad_end_seconds", 0) / 60))
        self._pad_end_spin = QSpinBox()
        self._pad_end_spin.setRange(-120, 120)
        self._pad_end_spin.setSuffix(" min")
        self._pad_end_spin.setValue(pad_end_default)
        self._pad_end_spin.setToolTip(
            "Signed offset on the end, minutes — prefilled from Settings "
            "▸ Recording. Positive runs over."
        )
        form.addRow("End padding:", self._pad_end_spin)

        vl.addLayout(form)

        note = QLabel(
            f"MetaTV must stay open to record. {provider_name} allows one "
            f"connection — recording will take it from playback."
        )
        note.setWordWrap(True)
        _theme.style_fn(
            note, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM};")
        vl.addWidget(note)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        _theme.style_fn(
            self._status_lbl,
            lambda: f"color: {_theme.COLOR_WARN}; font-size: {_theme.FONT_SM};")
        vl.addWidget(self._status_lbl)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        vl.addWidget(self._buttons)

        self._update_state()

    # ── validation ───────────────────────────────────────────────────────────

    def _validate(self) -> "tuple[bool, str]":
        """Return ``(ok_to_accept, note_text)``.

        ``ok_to_accept`` is False only for the two windows that can never be
        recorded: end at or before start, and a window that has already
        ended. A window that already STARTED (but has not ended) is valid —
        the note just says the recording begins now rather than at the
        original start, since ``RecordingManager`` picks up any window whose
        effective start has already passed on its next poll tick.
        """
        start = self._start_edit.dateTime().toPyDateTime()
        end = self._end_edit.dateTime().toPyDateTime()
        if end <= start:
            return False, "End time must be after the start time."
        if end <= self._now:
            return False, "This window has already ended."
        if start < self._now:
            return True, ("This window already started — recording begins "
                         "now, not at the original start time.")
        return True, ""

    def _update_state(self, *_args) -> None:
        ok, message = self._validate()
        self._status_lbl.setText(message)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    # ── result ───────────────────────────────────────────────────────────────

    def result_window(self) -> "tuple[datetime, datetime, int, int]":
        """The accepted window, converted for ``RecordingManager.schedule()``.

        Returns:
            ``(starts_at_utc_naive, ends_at_utc_naive, pad_start_seconds,
            pad_end_seconds)``. Call only after ``exec()`` returns Accepted.
        """
        start_local = self._start_edit.dateTime().toPyDateTime()
        end_local = self._end_edit.dateTime().toPyDateTime()
        return (
            to_utc_naive(start_local),
            to_utc_naive(end_local),
            self._pad_start_spin.value() * 60,
            self._pad_end_spin.value() * 60,
        )
