"""A live view of the log, for when something goes wrong and the app is open.

The logs already existed and were already reachable — Tools ▸ Open config
folder reveals the directory. That is the right answer for sending a file to
someone; it is the wrong answer for watching what the app is doing RIGHT NOW,
which is when a user actually wants a log: the thing they are trying to
reproduce is happening while they hunt for a text editor.

So this floats (``Qt.WindowType.Tool``), can be pushed to one side, and fills
itself as the app runs.

WHY A SIGNAL AND NOT A DIRECT WRITE
-----------------------------------
loguru calls its sinks on whatever thread emitted the record, and this app logs
from EPG fetches, the series monitor, ingestion workers and the UI. A sink that
touched a widget would be touching Qt from a worker thread, which is the crash
this codebase already has a rule about. ``_LogBridge`` is a ``QObject`` whose
only job is to turn a sink call into a queued signal, so the text arrives on the
main thread like every other cross-thread result here.

WHY THE BUFFER IS CAPPED
------------------------
The app can emit tens of thousands of lines a minute during ingestion — 1.44M
lines in a week on the owner's machine, before the volume fix. An uncapped
``QPlainTextEdit`` would grow without limit while the window sat open in a
corner, which is a memory leak with a scrollbar. The cap is a document-block
maximum, so the widget itself drops the oldest lines.
"""

from __future__ import annotations

import platform
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable

if TYPE_CHECKING:
    from metatv.core.config import Config

#: Lines kept in the view. Roughly a screenful times a few hundred — enough to
#: scroll back through what just happened, bounded so an open window cannot
#: grow without limit during an ingestion storm.
MAX_LINES = 5_000

#: Levels offered in the filter, coarsest last. loguru's own ordering.
LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")

#: What the viewer subscribes at. The FILE sink is INFO by default (see
#: __main__), but this window is opened deliberately, by someone who wants to
#: see everything — so it takes DEBUG and filters in the UI, where the choice
#: is reversible without a restart.
STREAM_LEVEL = "DEBUG"


class _LogBridge(QObject):
    """Turns a loguru sink call on any thread into a main-thread signal."""

    line = pyqtSignal(str, str)  # (level name, formatted line)

    def write(self, message) -> None:
        """loguru sink entry point. Runs on the emitting thread.

        Args:
            message: A loguru ``Message`` — a str carrying ``.record``.
        """
        try:
            record = message.record
            self.line.emit(record["level"].name, str(message).rstrip("\n"))
        except Exception:  # silent: a sink that raises would break logging
            # itself, and the failure has nowhere left to be reported.
            pass


class LogViewerWindow(QWidget):
    """Floating window that streams the log and offers the usual diagnostics."""

    def __init__(self, config: "Optional[Config]" = None, parent=None) -> None:
        """
        Args:
            config: The loaded config, used to locate the log directory.
            parent: Optional Qt parent.
        """
        super().__init__(parent, Qt.WindowType.Tool)
        self._config = config
        self._sink_id: Optional[int] = None
        self._buffer: deque[tuple[str, str]] = deque(maxlen=MAX_LINES)

        self.setWindowTitle("MetaTV — Log")
        self.resize(900, 520)
        self._build_ui()
        self._attach_sink()

    # ── construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        controls.addWidget(QLabel("Level"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(LEVELS)
        self.level_combo.setCurrentText("INFO")
        self.level_combo.setToolTip(
            "Hide lines below this level. The window always receives DEBUG, so "
            "raising and lowering this re-filters what is already here."
        )
        self.level_combo.currentTextChanged.connect(self._rerender)
        controls.addWidget(self.level_combo)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setToolTip("Show only lines containing this text")
        self.filter_edit.textChanged.connect(self._rerender)
        controls.addWidget(self.filter_edit, 1)

        self.follow_check = QCheckBox("Follow")
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip(
            "Scroll to the newest line as it arrives. Untick to hold your "
            "place while reading."
        )
        controls.addWidget(self.follow_check)

        root.addLayout(controls)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(QFont(_monospace_family()))
        _theme.style(self.view, "LOG_STREAM")
        root.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, tip, slot in (
            (f"{_icons.save_log_icon}  Save log…",
             "Write everything currently in this window to a file",
             self.save_log),
            (f"{_icons.copy_icon}  Copy diagnostics",
             "Copy version, platform and data-location details for a bug report",
             self.copy_diagnostics),
            (f"{_icons.config_folder_icon}  Open log folder",
             "Reveal the folder holding every log file, including rotated ones",
             self.open_log_folder),
            (f"{_icons.clear_log_icon}  Clear log files",
             "Delete every log file on disk, including rotated copies",
             self.clear_log_files),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            set_clickable(btn)
            buttons.addWidget(btn)
        buttons.addStretch(1)

        self.clear_view_btn = QPushButton("Clear view")
        self.clear_view_btn.setToolTip(
            "Empty this window without touching the files on disk"
        )
        self.clear_view_btn.clicked.connect(self.clear_view)
        set_clickable(self.clear_view_btn)
        buttons.addWidget(self.clear_view_btn)

        root.addLayout(buttons)

        self.status_lbl = QLabel("")
        # META_HINT, not a new role: it is already "small text, body colour",
        # which is exactly what this line is. A LOG_STATUS defined here would
        # have been a duplicate shape (the theme suite counts those) and would
        # have reached for COLOR_MUTED, which cannot clear 4.5:1 on any surface.
        _theme.style(self.status_lbl, "META_HINT")
        root.addWidget(self.status_lbl)
        self._update_status()

    # ── the live stream ─────────────────────────────────────────────────

    def _attach_sink(self) -> None:
        """Subscribe to loguru. Removed again in :meth:`closeEvent`."""
        self._bridge = _LogBridge()
        self._bridge.line.connect(self._on_line, Qt.ConnectionType.QueuedConnection)
        self._sink_id = logger.add(
            self._bridge.write, level=STREAM_LEVEL, format="{time:HH:mm:ss} | "
            "{level: <8} | {name}:{function}:{line} - {message}",
        )

    def _detach_sink(self) -> None:
        """Unsubscribe. Safe to call twice."""
        if self._sink_id is None:
            return
        try:
            logger.remove(self._sink_id)
        except ValueError:  # silent: loguru already dropped it (a reset
            # elsewhere); the subscription is gone either way, which is the
            # outcome this method exists to produce.
            pass
        self._sink_id = None

    def _on_line(self, level: str, line: str) -> None:
        """Main-thread slot: buffer the line and render it if it passes."""
        self._buffer.append((level, line))
        if self._passes(level, line):
            self._append(line)
        self._update_status()

    def _passes(self, level: str, line: str) -> bool:
        try:
            floor = LEVELS.index(self.level_combo.currentText())
            rank = LEVELS.index(level)
        except ValueError:
            floor, rank = 0, 0
        if rank < floor:
            return False
        needle = self.filter_edit.text().strip()
        return not needle or needle.casefold() in line.casefold()

    def _append(self, line: str) -> None:
        at_bottom = self.follow_check.isChecked()
        self.view.appendPlainText(line)
        if at_bottom:
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _rerender(self) -> None:
        """Re-apply the filters to the whole buffer.

        The buffer holds every line the window has received, unfiltered, so
        changing the level or the search re-reveals lines rather than requiring
        them to be logged again.
        """
        self.view.setPlainText(
            "\n".join(ln for lvl, ln in self._buffer if self._passes(lvl, ln))
        )
        if self.follow_check.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._update_status()

    def _update_status(self) -> None:
        shown = sum(1 for lvl, ln in self._buffer if self._passes(lvl, ln))
        total = len(self._buffer)
        suffix = "" if shown == total else f" of {total:,}"
        cap = " (oldest dropped)" if total == MAX_LINES else ""
        self.status_lbl.setText(f"{shown:,} line(s) shown{suffix}{cap}")

    # ── actions ─────────────────────────────────────────────────────────

    def clear_view(self) -> None:
        """Empty the window. The files on disk are untouched."""
        self._buffer.clear()
        self.view.clear()
        self._update_status()

    def save_log(self) -> None:
        """Write what is currently shown to a file the user picks."""
        default = f"metatv-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save log", default, "Text (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.view.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save log", f"Could not write the file:\n{exc}")
            return
        self.status_lbl.setText(f"Saved to {path}")

    def copy_diagnostics(self) -> None:
        """Put the details a bug report needs on the clipboard.

        Deliberately facts about the INSTALL, never about the subscription: no
        provider name, URL, or credential goes near this. The log lines
        themselves are already redacted by the patcher in ``__main__``, but a
        summary block assembled here would bypass that entirely.
        """
        QApplication.clipboard().setText(self.diagnostics_text())
        self.status_lbl.setText("Diagnostics copied to the clipboard")

    def diagnostics_text(self) -> str:
        """Return the diagnostics block. Separate from the clipboard for tests.

        Returns:
            A short plain-text summary of the install.
        """
        from metatv.core.log_paths import active_log_file, all_log_files

        try:
            from metatv.core.build_info import window_title
            build = window_title()
        except Exception:  # silent: the build id is a nicety in a support
            # block. Reporting its absence into the log the user is about to
            # copy would be noise about the diagnostics themselves, and
            # "unknown" already says everything a reader needs.
            build = "unknown"

        logs = all_log_files(self._config)
        total = 0
        for p in logs:
            try:
                total += p.stat().st_size
            except OSError:  # silent: a file that vanished between the listing
                # and the stat simply does not count toward the total.
                continue
        return "\n".join((
            f"build      : {build}",
            f"python     : {sys.version.split()[0]}",
            f"platform   : {platform.platform()}",
            f"log file   : {active_log_file(self._config)}",
            f"log files  : {len(logs)} totalling {total / 1_048_576:.1f} MB",
        ))

    def open_log_folder(self) -> None:
        """Reveal the log directory in the system file manager."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        from metatv.core.log_paths import log_directory

        d = log_directory(self._config, create=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def clear_log_files(self) -> None:
        """Delete every log file on disk, rotated copies included.

        All of them, not just the active one: rotation is what produced 330 MB
        on the owner's machine, so clearing only ``metatv.log`` would look like
        it worked and free almost nothing.

        The active file is truncated rather than unlinked — loguru holds it
        open, and removing it on Windows fails outright while on POSIX it
        leaves the handle writing to an unlinked inode, which reads as "the log
        stopped working".
        """
        removed, freed = clear_log_files(self._config)
        self.status_lbl.setText(
            f"Cleared {removed} file(s), freeing {freed / 1_048_576:.1f} MB"
        )

    # ── lifetime ────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Unsubscribe from loguru before the window goes away.

        A sink outliving its widget would call into a deleted C++ object on the
        next log line from any thread — the same fault that has been aborting
        this app's shutdown.

        Args:
            event: The Qt close event.
        """
        self._detach_sink()
        super().closeEvent(event)


def clear_log_files(config: "Optional[Config]" = None) -> tuple[int, int]:
    """Delete the log files, truncating the one loguru still holds open.

    Module-level so Tools ▸ Clear log can do it without opening the viewer, and
    so the viewer's button and the menu item cannot drift into two answers.

    Args:
        config: The loaded config, used to locate the log directory.

    Returns:
        ``(files_cleared, bytes_freed)``.
    """
    from metatv.core.log_paths import active_log_file, all_log_files

    active = active_log_file(config)
    removed = freed = 0
    for path in all_log_files(config):
        try:
            size = path.stat().st_size
        except OSError:  # silent: already gone; nothing to clear or count.
            continue
        try:
            if path == active:
                # Truncate, never unlink: loguru holds this handle open.
                with path.open("w", encoding="utf-8"):
                    pass
            else:
                path.unlink()
        except OSError as exc:
            logger.warning("Could not clear {}: {}", path.name, exc)
            continue
        removed += 1
        freed += size
    logger.info("Cleared {} log file(s), freeing {} bytes", removed, freed)
    return removed, freed


def _monospace_family() -> str:
    """Return a monospace family Qt will actually resolve on this platform.

    ``QFont("monospace")`` is not a real family on macOS or Windows; Qt's
    ``StyleHint`` is the portable way to ask, and the explicit families are
    there so the hint has something good to land on.
    """
    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font.defaultFamily()
