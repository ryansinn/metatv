"""Settings → Downloads: the library folder, layout choice and free-space floor.

Its own module rather than one more method on ``SettingsTabsMixin``:
``settings_dialog_tabs.py`` is baselined by ``tests/code_health_baseline.json``
(CLAUDE.md — a pinned file at its ceiling means extract to a cohesive new
module, not rebaseline), and this tab is a self-contained concern the same way
``channel_downloads.py`` was split out of ``channel.py`` for the identical
reason.

Settled in *Catch, Keep, Record* (2026-08-30): the library folder, the
tree/flat layout choice and the free-space floor all shipped as hardcoded
defaults (#656) with the note that "the layout and the floor are not yet in
Settings, so they use those defaults for now." This is that page.

The widgets read/write the same ``config.download_*`` fields
``download_manager.py`` already reads live on every scheduler step
(``library_dir``, ``destination_for``, ``_space_shortfall``), so nothing here
needs an entry in ``settings_apply.HANDLERS`` — unlike, say,
``series_monitor_interval_minutes``, which only takes effect once the timer
re-arms.
"""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from metatv.core.download_naming import LAYOUT_FLAT, LAYOUT_TREE


class SettingsDownloadsTabMixin:
    """The Downloads tab builder + its one direct UI callback.

    Mixed into ``SettingsDialog`` alongside ``SettingsTabsMixin`` — same shape
    as that split from ``settings_dialog.py``: ``self._download_dir_input``
    etc. (read by ``SettingsDialog._load_values``/``_save_values``) resolve
    exactly as if this method lived there, because Python attribute lookup
    doesn't care which file defined the method that set them.
    """

    def _build_downloads_tab(self) -> QWidget:
        """Build the Downloads page."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        folder_group = QGroupBox("Library folder")
        folder_form = QFormLayout(folder_group)
        folder_form.setSpacing(8)

        folder_row = QHBoxLayout()
        self._download_dir_input = QLineEdit()
        self._download_dir_input.setToolTip(
            "Where finished downloads are saved. Created automatically the\n"
            "first time something downloads to it."
        )
        folder_row.addWidget(self._download_dir_input, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_download_dir)
        folder_row.addWidget(browse_btn)
        folder_form.addRow("Downloads folder:", folder_row)

        self._download_layout_combo = QComboBox()
        self._download_layout_combo.addItem(
            "Media-server tree (Movies/, Series/Show/Season NN/)",
            userData=LAYOUT_TREE)
        self._download_layout_combo.addItem(
            "Flat — one folder", userData=LAYOUT_FLAT)
        self._download_layout_combo.setToolTip(
            "Tree (default): Plex, Jellyfin and Kodi read this layout without\n"
            "any configuration.\n\n"
            "An item MetaTV does not know enough about (no year, no season/\n"
            "episode number) still lands flat rather than in a made-up folder\n"
            "like Series/Unknown/Season 00/ — that fallback applies per item,\n"
            "whichever layout you pick here.\n\n"
            "Flat: every download in one folder, filename only."
        )
        folder_form.addRow("Layout:", self._download_layout_combo)
        layout.addWidget(folder_group)

        space_group = QGroupBox("Free-space floor")
        space_form = QFormLayout(space_group)
        space_form.setSpacing(8)

        self._download_floor_spin = QDoubleSpinBox()
        self._download_floor_spin.setRange(0, 1000)
        self._download_floor_spin.setSingleStep(1)
        self._download_floor_spin.setDecimals(1)
        self._download_floor_spin.setSuffix(" GB")
        self._download_floor_spin.setSpecialValueText("Off")
        self._download_floor_spin.setToolTip(
            "Stop downloading before free space on this disk falls below\n"
            "this many GB. 0 (Off) removes the floor entirely.\n\n"
            "Checked against ACTUAL free space, not against bytes\n"
            "downloaded — the floor protects the disk, not the library."
        )
        space_form.addRow("Keep at least:", self._download_floor_spin)

        self._download_policy_combo = QComboBox()
        self._download_policy_combo.addItem(
            "Finish the current download, then stop", userData="finish_current")
        self._download_policy_combo.addItem(
            "Stop immediately", userData="stop_now")
        self._download_policy_combo.setToolTip(
            "What to do once a download would take free space below the\n"
            "floor.\n\n"
            "\"Finish the current download\" is honoured only when what is\n"
            "left of it actually fits inside the floor — if it does not,\n"
            "MetaTV stops immediately regardless of this setting, and the\n"
            "queue row says why."
        )
        space_form.addRow("When the floor is reached:", self._download_policy_combo)
        layout.addWidget(space_group)

        layout.addStretch()
        return tab

    def _browse_download_dir(self) -> None:
        """"Browse…" next to the downloads-folder path."""
        start = os.path.expanduser(self._download_dir_input.text().strip() or "~")
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose downloads folder", start)
        if chosen:
            self._download_dir_input.setText(chosen)
