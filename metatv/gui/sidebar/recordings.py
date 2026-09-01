"""The Recordings sidebar section — what is scheduled and what is running.

Sibling of :mod:`metatv.gui.sidebar.downloads`, and separate from it on
purpose. *Catch, Keep, Record* (2026-08-30): **"Downloads/ and Recordings/
side by side"** — separate surfaces, not a combined Library.

They are separate because the axis between them is RECOVERABILITY, which is
the same axis the connection accountant arbitrates on: a VOD is still there in
an hour, a live moment is not. That is why a recording is never preempted and
why its rows say something a download's never has to — how long is left on a
window that will not come round again.

Progress here is **wall-clock**, not bytes: a live stream has no total size, so
the only honest bar is how far through the window it is. That is
``RecordingProgress.elapsed_fraction``, which takes ``now`` rather than
reaching for it — so this section renders a fixed moment and a test can pin one.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QSizePolicy

from metatv.core.epg_utils import now_utc, to_local
from metatv.gui import icons as _icons
from metatv.gui.sidebar.base import CollapsibleSection, SectionAction, make_seamless
from metatv.gui.sidebar.transfer_rows import (
    ROLE_CHANNEL_ID, ROLE_DEST_PATH, ROLE_ITEM_ID, ROLE_STATE,
    add_transfer_row, human_bytes,
)

#: State -> the word the user reads. Never a colour on its own.
_STATE_WORDS: dict[str, str] = {
    "scheduled": "Scheduled",
    "recording": "Recording",
    "completed": "Recorded",
    "failed":    "Failed",
    "cancelled": "Cancelled",
}
#: A scheduled recording whose source is busy. Distinct from plain "Scheduled"
#: because it is the one state where the user may still act — stop what is
#: using the connection — and a silent wait is indistinguishable from a
#: broken feature.
_WAITING_WORD = "Waiting for the source"


def recording_state_word(state: str, waiting_for_slot: bool = False) -> str:
    """The user-facing word for a recording state."""
    if waiting_for_slot and state in ("scheduled", "recording"):
        return _WAITING_WORD
    return _STATE_WORDS.get(state, state.title())


class RecordingsSection(CollapsibleSection):
    """Recordings scheduled, running and finished."""

    MIN_ROWS: int = 3

    itemSelected             = pyqtSignal(str)   # channel_id — open its details
    openLibraryFolderClicked = pyqtSignal()      # the section's folder button
    watchRequested           = pyqtSignal(str)   # recording_id — watch the growing file
    cancelRequested          = pyqtSignal(str)   # recording_id
    extendRequested          = pyqtSignal(str)   # recording_id

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Recordings", _icons.record_icon, config, parent,
                         vector_role="record")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self) -> str:
        return "recordings"

    def budgeted_list(self):
        return self.__dict__.get("recordings_list")

    def item_count(self) -> int | None:
        lst = self.__dict__.get("recordings_list")
        return None if lst is None else self.count_content_rows(lst)

    def overflow_actions(self):
        return [
            SectionAction(
                f"{_icons.config_folder_icon} Open recordings folder",
                "Show the folder your recordings are saved in",
                self.openLibraryFolderClicked.emit,
                icon="folder_open",
            ),
        ]

    def create_content(self) -> None:
        self.recordings_list = QListWidget()
        self.recordings_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recordings_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recordings_list.itemSelectionChanged.connect(self._emit_selected)
        make_seamless(self.recordings_list)
        self.content_layout.addWidget(self.recordings_list)

    def _emit_selected(self) -> None:
        item = self.recordings_list.currentItem()
        if item is None:
            return
        channel_id = item.data(ROLE_CHANNEL_ID)
        if channel_id:
            self.itemSelected.emit(channel_id)

    # ── the one render seam ────────────────────────────────────────────────
    def refresh_progress(self, rows, *, now: "datetime | None" = None) -> None:
        """Render ``RecordingManager.progress()`` output.

        Args:
            rows: ``list[RecordingProgress]``.
            now: The moment to measure against. Taken rather than reached for,
                so the bar is reproducible and a test can pin one — the same
                contract ``elapsed_fraction`` already has.
        """
        lst = self.__dict__.get("recordings_list")
        if lst is None:
            return
        now = now or now_utc()
        lst.clear()
        for row in rows or ():
            running = row.state == "recording"
            # A scheduled recording has no progress yet — no bar, rather than a
            # bar at zero, which reads as stalled instead of as not-started.
            fraction = row.elapsed_fraction(now=now) if running else None
            when = to_local(row.starts_at).strftime("%H:%M")
            size = human_bytes(row.recorded_bytes) if row.recorded_bytes else ""
            meta = [row.channel_name, when]
            if size:
                meta.append(size)
            add_transfer_row(
                lst,
                item_id=row.recording_id,
                channel_id=row.channel_id,
                title=row.programme_title or row.channel_name,
                state=row.state,
                state_word=recording_state_word(row.state, row.waiting_for_slot),
                fraction=fraction,
                meta_parts=tuple(m for m in meta if m),
                dest_path=row.dest_path or "",
                tooltip=row.error or f"{to_local(row.starts_at):%H:%M}–{to_local(row.ends_at):%H:%M}",
            )
        self.set_empty(lst.count() == 0)
        self.reapply_row_budget()

    def selected_recording(self) -> "tuple[str, str, str] | None":
        """``(recording_id, state, dest_path)`` for the current row, or None."""
        lst = self.__dict__.get("recordings_list")
        item = lst.currentItem() if lst else None
        if item is None:
            return None
        return (item.data(ROLE_ITEM_ID), item.data(ROLE_STATE),
                item.data(ROLE_DEST_PATH) or "")
