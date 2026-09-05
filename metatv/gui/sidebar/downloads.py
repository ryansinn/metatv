"""The Downloads sidebar section — what is happening right now, and what
finished.

Settled in *Catch, Keep, Record* (2026-08-30), and the split matters because
it is what stops this becoming a second browse surface:

    Center panel: a scope on the channel list, not a second browse surface.
    A bespoke Downloads view would rebuild what the channel list already has —
    the row grammar, the details pane, play, resume, context menus — and
    MetaTV's recurring failure is the parallel path, not the missing one. The
    sidebar section stays, because it answers a different question: the scope
    is "what do I have", the section is "what is happening right now".

So this section is deliberately small. It shows transfers in flight under an
"In progress" heading, and what finished under History's own Today/Yesterday/…
segments (bucketed by ``DownloadDB.updated_at`` — a download's row IS its
history, so a group's "forget" purges those rows rather than nulling a flag;
see ``DownloadManager.clear_history_group``). Anything about *browsing* what
you already have belongs to the Downloaded scope on the channel list, not here.

The rows come from ``DownloadManager.progress()`` — plain DTOs, pushed in by
the host, never an ORM row across a thread and never a manager reference held
by a widget.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QSizePolicy

from metatv.core.download_manager import TERMINAL_STATES
from metatv.core.epg_utils import to_local_naive
from metatv.core.history_buckets import BUCKETS, bucket_for
from metatv.core.repositories.channel_downloads import _file_exists
from metatv.gui import deferred_config_save as _cfgsave
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.chip_row import DENSITY_COMFORTABLE
from metatv.gui.sidebar.base import (
    CollapsibleSection, GroupHeading, SectionAction, make_seamless,
)
from metatv.gui.sidebar.transfer_rows import (
    ROLE_CHANNEL_ID, ROLE_DEST_PATH, ROLE_ITEM_ID, ROLE_STATE,
    add_transfer_row, human_bytes, human_eta, human_rate,
)
from metatv.gui.token_color import to_qcolor

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

#: Marks a list item as chrome (a group heading or the connection-gate note)
#: rather than a download row. Read by every click/selection guard, which must
#: skip chrome the same way History's headings do — ``UserRole`` alone is not
#: enough, because ``itemAt()`` still returns a heading under the cursor.
_ROLE_BUCKET = Qt.ItemDataRole.UserRole + 4


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
    """Transfers in flight, and finished downloads under History's segments."""

    MIN_ROWS: int = 3

    itemSelected            = pyqtSignal(str)   # channel_id — open its details
    openLibraryFolderClicked = pyqtSignal()     # the section's folder button
    revealItemRequested     = pyqtSignal(str)   # dest_path — reveal THIS file
    pauseRequested          = pyqtSignal(str)   # download_id
    resumeRequested         = pyqtSignal(str)   # download_id
    cancelRequested         = pyqtSignal(str)   # download_id
    playRequested           = pyqtSignal(str)   # download_id — play the finished file
    #: One history group's clear — the per-heading "forget" control. Same
    #: name and shape as ``HistorySection``'s signal; a different section
    #: instance, so there is no ambiguity in wiring either up.
    clearHistoryGroupClicked = pyqtSignal(str)
    #: The overflow's "Clear download history" — every finished/failed row.
    clearDownloadHistoryClicked = pyqtSignal()

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
        paused = bool(getattr(self.config, "downloads_paused", False))
        return [
            SectionAction(
                (f"{_icons.play_icon} Resume all downloads" if paused
                 else f"{_icons.enrich_pause_icon} Pause all downloads"),
                ("Resume every queued or paused download" if paused
                 else "Hold every download until you resume them yourself"),
                self._toggle_downloads_paused,
            ),
            SectionAction(
                f"{_icons.delete_icon} Clear download history",
                "Remove every finished or failed download from your history "
                "— files already saved are never deleted",
                self.clearDownloadHistoryClicked.emit,
                destructive=True,
            ),
            SectionAction(
                f"{_icons.config_folder_icon} Open downloads folder",
                "Show the folder your downloads are saved in",
                self.openLibraryFolderClicked.emit,
                icon="folder_open",
            ),
        ]

    def _toggle_downloads_paused(self) -> None:
        """Flip ``config.downloads_paused`` — the ⋯ menu's Pause/Resume all.

        Nothing else to wire up: ``DownloadManager._step`` already reads this
        live, and every queued/paused row's ``reason`` already explains it
        (``DownloadManager._reason_for``) — the next refresh tick shows both.
        """
        self.config.downloads_paused = not bool(
            getattr(self.config, "downloads_paused", False))
        try:
            _cfgsave.save_soon(self)
        except Exception as exc:  # noqa: BLE001 — never break the toggle on a save fault
            logger.warning(f"Could not save downloads_paused: {exc}")

    def create_content(self) -> None:
        self.downloads_list = QListWidget()
        self.downloads_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.downloads_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.downloads_list.itemSelectionChanged.connect(self._emit_selected)
        self.downloads_list.itemDoubleClicked.connect(self._on_double_clicked)
        make_seamless(self.downloads_list)
        self.content_layout.addWidget(self.downloads_list)

    def _emit_selected(self) -> None:
        item = self.downloads_list.currentItem()
        if item is None or item.data(_ROLE_BUCKET) is not None:
            return
        channel_id = item.data(ROLE_CHANNEL_ID)
        if channel_id:
            self.itemSelected.emit(channel_id)

    def _on_double_clicked(self, item) -> None:
        """Double-click plays a FINISHED download. Every other row is a no-op
        here — pause/resume/cancel/play-when-missing stay deliberate actions
        in the context menu, not something a stray double-click can trigger.
        """
        if item is None or item.data(_ROLE_BUCKET) is not None:
            return
        if item.data(ROLE_STATE) != "completed":
            return
        download_id = item.data(ROLE_ITEM_ID)
        if download_id:
            self.playRequested.emit(download_id)

    # ── the one render seam ────────────────────────────────────────────────
    def refresh_progress(self, rows, gate_lines=(), *, now=None) -> None:
        """Render ``DownloadManager.progress()`` output.

        Pushed by the host rather than pulled by the widget, matching
        ``refresh_retry``: the host owns the manager, the section renders what
        it is handed, and neither needs the other's lifetime.

        Args:
            rows: ``list[DownloadProgress]``.
            gate_lines: ``DownloadManager.connection_gate_lines()`` output —
                zero or more "<provider> · N of M connections in use" lines,
                shown above everything else so a blocked queue explains itself
                without opening a row.
            now: The local moment to bucket completed/failed rows against;
                taken rather than reached for, so a test can pin one instead
                of sleeping — the same contract ``RecordingsSection.
                refresh_progress`` already has. Defaults to ``datetime.now()``.
        """
        lst = self.__dict__.get("downloads_list")
        if lst is None:
            return
        lst.clear()
        rows = list(rows or ())

        for line in gate_lines or ():
            self._add_gate_line(lst, line)

        active = [r for r in rows if r.state not in TERMINAL_STATES]
        history = [r for r in rows if r.state in TERMINAL_STATES]

        if active:
            self._add_active_heading(lst, len(active))
            for row in active:
                self._add_download_row(lst, row)

        if history:
            now = now or datetime.now()
            grouped: dict[str, list] = {}
            for row in history:
                when = to_local_naive(row.updated_at) if row.updated_at else None
                grouped.setdefault(bucket_for(when, now=now), []).append(row)
            for bucket in BUCKETS:
                group_rows = grouped.get(bucket.key)
                if not group_rows:
                    continue
                self._add_history_group_heading(lst, bucket, len(group_rows))
                for row in group_rows:
                    self._add_download_row(lst, row)

        self.set_empty(lst.count() == 0)
        self.reapply_row_budget()

    @staticmethod
    def _add_gate_line(lst, text: str) -> None:
        """One non-selectable, muted note — the connection gate for one provider."""
        item = QListWidgetItem(f"{_icons.info_icon} {text}")
        item.setData(_ROLE_BUCKET, "__gate__")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(to_qcolor(_theme.COLOR_MUTED))
        lst.addItem(item)

    @staticmethod
    def _add_active_heading(lst, count: int) -> None:
        """"In progress" — a count only. Nothing to forget, so no clear control."""
        item = QListWidgetItem(lst)
        item.setData(_ROLE_BUCKET, "__active__")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        heading = GroupHeading("In progress", count)
        item.setSizeHint(QSize(0, heading.sizeHint().height()))
        lst.setItemWidget(item, heading)

    def _add_history_group_heading(self, lst, bucket, count: int) -> None:
        """One time-group heading, with its own "forget these" control.

        Mirrors ``HistorySection._add_group_heading`` — same button, same
        role, same theme sheet, because it is the same idea: a group's own
        destructive control, distinct from the section-wide "Clear download
        history" in the ⋯ menu. Deletes ``DownloadDB`` rows (never files) —
        see ``DownloadManager.clear_history_group``.
        """
        item = QListWidgetItem(lst)
        item.setData(_ROLE_BUCKET, bucket.key)
        item.setFlags(Qt.ItemFlag.NoItemFlags)

        forget = QPushButton()
        forget.setFixedSize(20, 20)
        forget.setToolTip(f"Forget everything under {bucket.label}")
        forget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        def _paint_glyph() -> str:
            forget.setIcon(_icon_utils.resolve_icon(
                _icons.vector_key("delete"), _theme.COLOR_TEXT))
            forget.setIconSize(QSize(13, 13))
            return _theme.HISTORY_GROUP_FORGET_BUTTON

        _theme.style_fn(forget, _paint_glyph)
        forget.clicked.connect(
            lambda _checked=False, key=bucket.key:
            self.clearHistoryGroupClicked.emit(key)
        )

        heading = GroupHeading(
            bucket.label, count,
            tooltip=f"{count} finished — {bucket.label.lower()}",
            trailing_button=forget,
        )
        item.setSizeHint(QSize(0, heading.sizeHint().height()))
        lst.setItemWidget(item, heading)

    def _add_download_row(self, lst, row) -> None:
        add_transfer_row(
            lst,
            item_id=row.id,
            channel_id=row.channel_id,
            title=row.channel_name,
            state=row.state,
            state_word=download_state_word(row.state, row.paused_by_playback),
            fraction=row.fraction,
            meta_parts=self._meta_parts(row),
            dest_path=row.dest_path or "",
            tooltip=row.error or row.reason or "",
            # Always comfortable, never the user's general sidebar-density
            # preference: the second line here (why it's stuck, how fast, how
            # long left) is the thing this section exists to show, not a
            # decorative extra — and the shared row builder already collapses
            # back to one line by itself whenever there is nothing to say
            # (an empty meta line renders no second line at all).
            density=DENSITY_COMFORTABLE,
        )

    @staticmethod
    def _meta_parts(row) -> "tuple[str, ...]":
        """The row's second line, by state — never a second formatter.

        Running: size, rate, ETA — joined by ``add_transfer_row``'s own
        ``sidebar_meta_line``, not re-joined here. Queued/paused: the
        manager's own ``reason`` (why it is not moving right now). Failed:
        its error. Completed: the file's size, plus "file removed" when
        ``channel_downloads._file_exists`` disagrees with the ledger — the
        same DL-2 check the Downloaded scope runs.
        """
        if row.state == "running":
            total = human_bytes(row.total_bytes)
            done = human_bytes(row.downloaded_bytes)
            size = f"{done} of {total}" if total else done
            return tuple(p for p in (
                size, human_rate(row.bytes_per_second), human_eta(row.eta_seconds),
            ) if p)
        if row.state == "completed":
            size = human_bytes(row.total_bytes or row.downloaded_bytes)
            if _file_exists(row.dest_path):
                return (size,) if size else ()
            return (size, "file removed") if size else ("file removed",)
        if row.state == "failed":
            return (row.error or "Failed",)
        return (row.reason,) if row.reason else ()

    def selected_download(self) -> "tuple[str, str, str] | None":
        """``(download_id, state, dest_path)`` for the current row, or None.

        One accessor rather than three lookups at each menu site — the context
        menu needs all three to decide what to offer. Returns None for chrome
        (a heading or the connection-gate note) the same way it does for no
        selection at all.
        """
        lst = self.__dict__.get("downloads_list")
        item = lst.currentItem() if lst else None
        if item is None or item.data(_ROLE_BUCKET) is not None:
            return None
        return (item.data(ROLE_ITEM_ID), item.data(ROLE_STATE),
                item.data(ROLE_DEST_PATH) or "")
