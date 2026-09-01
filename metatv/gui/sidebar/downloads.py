"""The Downloads sidebar section — what is happening right now.

Settled in *Catch, Keep, Record* (2026-08-30), and the split matters because
it is what stops this becoming a second browse surface:

    Center panel: a scope on the channel list, not a second browse surface.
    A bespoke Downloads view would rebuild what the channel list already has —
    the row grammar, the details pane, play, resume, context menus — and
    MetaTV's recurring failure is the parallel path, not the missing one. The
    sidebar section stays, because it answers a different question: the scope
    is "what do I have", the section is "what is happening right now".

So this section is deliberately small. It shows transfers in flight, their
state and their progress, and it offers the folder button. Anything about
*browsing* what you already have belongs to the Downloaded scope on the
channel list, not here.

The rows come from ``DownloadManager.progress()`` — plain DTOs, pushed in by
the host, never an ORM row across a thread and never a manager reference held
by a widget.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QSizePolicy

from metatv.gui import icons as _icons
from metatv.gui.sidebar.base import CollapsibleSection, SectionAction, make_seamless
from metatv.gui.sidebar.transfer_rows import (
    ROLE_CHANNEL_ID, ROLE_DEST_PATH, ROLE_ITEM_ID, ROLE_STATE,
    add_transfer_row, human_bytes,
)

#: State -> the word the user reads. Never a colour on its own.
#:
#: "Paused — playing" is the one that earns its length: a download that paused
#: itself because you pressed play is not the same event as one you paused, and
#: on a one-connection account the first is the scheduler working correctly
#: rather than something going wrong. The spec asks for exactly this: *"a
#: download pauses itself when you start watching and resumes when you stop,
#: and the row says which of those it is doing."*
_STATE_WORDS: dict[str, str] = {
    "queued":    "Queued",
    "running":   "Downloading",
    "paused":    "Paused",
    "completed": "Done",
    "failed":    "Failed",
}
_PAUSED_BY_PLAYBACK_WORD = "Paused — playing"


def download_state_word(state: str, paused_by_playback: bool = False) -> str:
    """The user-facing word for a download state.

    Args:
        state: The stored state string.
        paused_by_playback: True when the scheduler yielded the connection to
            playback, which reads differently from a pause the user asked for.
    """
    if state == "paused" and paused_by_playback:
        return _PAUSED_BY_PLAYBACK_WORD
    return _STATE_WORDS.get(state, state.title())


class DownloadsSection(CollapsibleSection):
    """Transfers in flight, with their state and progress."""

    MIN_ROWS: int = 3

    itemSelected            = pyqtSignal(str)   # channel_id — open its details
    openLibraryFolderClicked = pyqtSignal()     # the section's folder button
    revealItemRequested     = pyqtSignal(str)   # dest_path — reveal THIS file
    pauseRequested          = pyqtSignal(str)   # download_id
    resumeRequested         = pyqtSignal(str)   # download_id
    cancelRequested         = pyqtSignal(str)   # download_id

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Downloads", _icons.download_icon, config, parent,
                         vector_role="download")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self) -> str:
        return "downloads"

    def budgeted_list(self):
        return self.__dict__.get("downloads_list")

    def item_count(self) -> int | None:
        lst = self.__dict__.get("downloads_list")
        return None if lst is None else self.count_content_rows(lst)

    def overflow_actions(self):
        return [
            SectionAction(
                f"{_icons.config_folder_icon} Open downloads folder",
                "Show the folder your downloads are saved in",
                self.openLibraryFolderClicked.emit,
                icon="folder_open",
            ),
        ]

    def create_content(self) -> None:
        self.downloads_list = QListWidget()
        self.downloads_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.downloads_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.downloads_list.itemSelectionChanged.connect(self._emit_selected)
        make_seamless(self.downloads_list)
        self.content_layout.addWidget(self.downloads_list)

    def _emit_selected(self) -> None:
        item = self.downloads_list.currentItem()
        if item is None:
            return
        channel_id = item.data(ROLE_CHANNEL_ID)
        if channel_id:
            self.itemSelected.emit(channel_id)

    # ── the one render seam ────────────────────────────────────────────────
    def refresh_progress(self, rows) -> None:
        """Render ``DownloadManager.progress()`` output.

        Pushed by the host rather than pulled by the widget, matching
        ``refresh_retry``: the host owns the manager, the section renders what
        it is handed, and neither needs the other's lifetime.

        Args:
            rows: ``list[DownloadProgress]``.
        """
        lst = self.__dict__.get("downloads_list")
        if lst is None:
            return
        lst.clear()
        for row in rows or ():
            total = human_bytes(row.total_bytes)
            done = human_bytes(row.downloaded_bytes)
            meta = f"{done} of {total}" if total else done
            add_transfer_row(
                lst,
                item_id=row.id,
                channel_id=row.channel_id,
                title=row.channel_name,
                state=row.state,
                state_word=download_state_word(row.state, row.paused_by_playback),
                fraction=row.fraction,
                meta_parts=(meta,) if meta else (),
                dest_path=row.dest_path or "",
                tooltip=row.error or meta,
            )
        self.set_empty(lst.count() == 0)
        self.reapply_row_budget()

    def selected_download(self) -> "tuple[str, str, str] | None":
        """``(download_id, state, dest_path)`` for the current row, or None.

        One accessor rather than three lookups at each menu site — the context
        menu needs all three to decide what to offer.
        """
        item = self.downloads_list.currentItem() if self.__dict__.get("downloads_list") else None
        if item is None:
            return None
        return (item.data(ROLE_ITEM_ID), item.data(ROLE_STATE),
                item.data(ROLE_DEST_PATH) or "")
