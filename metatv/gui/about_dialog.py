"""About MetaTV — what this build is, and what it is built on.

Help ▸ About has existed as a menu item for a long time; ``show_about`` logged
"Show about" and returned. So the entry point was discoverable, did nothing,
and nobody noticed because nothing tested it.

Two jobs:

* answer "what am I running" — the first question of any support conversation,
  and the reason there is a one-click copy button;
* carry the open-source notices. mpv is not merely *used* here: CI vendors a
  copy of it, with its dylibs, into ``MetaTV.app/Contents/Resources/mpv/`` (see
  ``.github/workflows/release.yml``). Redistributing a GPL binary carries an
  obligation to say so and to point at the source, which nothing did.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from metatv.core.component_versions import ComponentVersions, collect
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

#: Third-party components redistributed with a packaged build.
#:
#: mpv is spawned as an external binary rather than linked as libmpv, and the
#: macOS bundle SHIPS it — so this is redistribution and the notice is owed.
#: Kept as data so a second bundled component is added here rather than by
#: editing a paragraph of prose.
BUNDLED_COMPONENTS: tuple[tuple[str, str, str], ...] = (
    (
        "mpv",
        "GPL v2 or later",
        "https://mpv.io  ·  source: https://github.com/mpv-player/mpv",
    ),
)


def describe(versions: ComponentVersions) -> str:
    """Plain-text version block — what the copy button puts on the clipboard.

    Text rather than rich markup so it can be pasted straight into a message
    or an issue, which is the only reason anyone presses that button.
    """
    build = versions.build_id or "source checkout"
    lines = [
        f"MetaTV {versions.app} ({build})",
        f"Python {versions.python}  ·  Qt {versions.qt}  ·  PyQt {versions.pyqt}",
        f"Platform: {versions.platform_name}",
    ]
    if versions.mpv:
        lines.append(f"mpv {versions.mpv}  ({versions.mpv_path})")
    elif versions.mpv_path:
        lines.append(f"mpv: could not read version from {versions.mpv_path}")
    else:
        lines.append("mpv: not found")
    return "\n".join(lines)


class AboutDialog(QDialog):
    """Version, component and licence information."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About MetaTV")
        self.setMinimumWidth(460)

        self._versions = collect()

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel(f"{_icons.info_icon}  MetaTV")
        _theme.style(title, "DIALOG_TITLE")
        root.addWidget(title)

        self._details = QLabel(describe(self._versions))
        self._details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._details.setWordWrap(True)
        _theme.style(self._details, "META_HINT")
        root.addWidget(self._details)

        notices = QLabel(self._licence_text())
        notices.setWordWrap(True)
        notices.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        _theme.style(notices, "META_HINT")
        root.addWidget(notices)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self._copy_btn = QPushButton("Copy details")
        self._copy_btn.setToolTip("Copy the version block to the clipboard")
        self._copy_btn.clicked.connect(self._copy_details)
        cursor_affordance.set_clickable(self._copy_btn)
        buttons.addWidget(self._copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        cursor_affordance.set_clickable(close_btn)
        buttons.addWidget(close_btn)

        root.addLayout(buttons)

    @staticmethod
    def _licence_text() -> str:
        """The open-source notices, built from BUNDLED_COMPONENTS."""
        lines = ["Playback is provided by software redistributed with this app:"]
        lines += [f"    {name} — {licence}\n    {where}"
                  for name, licence, where in BUNDLED_COMPONENTS]
        return "\n".join(lines)

    def _copy_details(self) -> None:
        """Put the version block on the clipboard and say so."""
        QApplication.clipboard().setText(describe(self._versions))
        self._copy_btn.setText("Copied")
