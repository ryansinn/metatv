"""Settings → Recording: the default start/end padding a new recording gets.

Its own module rather than one more method on ``SettingsTabsMixin``:
``settings_dialog_tabs.py`` is baselined by ``tests/code_health_baseline.json``
(CLAUDE.md — a pinned file at its ceiling means extract to a cohesive new
module, not rebaseline), and this tab is a self-contained concern the same way
``settings_downloads_tab.py`` was split out for the identical reason (DL-1).

Settled in *Catch, Keep, Record* (2026-09-04): ``RecordingManager.schedule()``
already applies signed start/end padding, stored per row, defaulting from
``config.recording_pad_start_seconds``/``_end_seconds``. This is the page that
lets that default be changed instead of living only in ``Config``'s field
defaults.

The widgets read/write ``config.recording_pad_start_seconds``/
``_end_seconds`` directly — ``RecordingManager.schedule()`` reads those fields
fresh on every call, so nothing here needs an entry in
``settings_apply.HANDLERS``.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QGroupBox, QSpinBox, QVBoxLayout, QWidget


class SettingsRecordingTabMixin:
    """The Recording tab builder.

    Mixed into ``SettingsDialog`` alongside ``SettingsTabsMixin`` — same shape
    as ``SettingsDownloadsTabMixin``: ``self._rec_pad_start_spin`` /
    ``self._rec_pad_end_spin`` (read by ``SettingsDialog._load_values``/
    ``_save_values``) resolve exactly as if this method lived there, because
    Python attribute lookup doesn't care which file defined the method that
    set them.
    """

    def _build_recording_tab(self) -> QWidget:
        """Build the Recording tab — the global default padding a new recording gets.

        Only the DEFAULT: ``RecordingManager.schedule()`` stores the offsets
        per row (signed, per-recording, defaulting from here), so changing
        this never rewrites a recording already scheduled. Minutes on
        screen, seconds in config — nobody thinks in 900 seconds.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        pad_group = QGroupBox("Default padding")
        pad_form = QFormLayout(pad_group)
        pad_form.setSpacing(8)

        self._rec_pad_start_spin = QSpinBox()
        self._rec_pad_start_spin.setRange(-120, 120)
        self._rec_pad_start_spin.setSuffix(" min")
        self._rec_pad_start_spin.setToolTip(
            "Signed offset on a recording's start, minutes. Negative starts "
            "earlier (skip a pregame hour with -60); positive starts later."
        )
        pad_form.addRow("Start padding:", self._rec_pad_start_spin)

        self._rec_pad_end_spin = QSpinBox()
        self._rec_pad_end_spin.setRange(-120, 120)
        self._rec_pad_end_spin.setSuffix(" min")
        self._rec_pad_end_spin.setToolTip(
            "Signed offset on a recording's end, minutes. Positive runs over "
            "(sport overruns, always); negative ends earlier."
        )
        pad_form.addRow("End padding:", self._rec_pad_end_spin)

        layout.addWidget(pad_group)
        layout.addStretch()
        return tab
