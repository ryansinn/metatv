"""The row both transfer sections draw, and the words they use for a state.

Downloads and Recordings are the same shape — a title, what it is doing, and
how far through it is — so they share a builder rather than each growing one.
The spec's own reason for building the engines together applies to the rows:
*"Downloads and recording are the same transfer, the same queue, the same
connection accounting and the same resume logic — differing only in whether a
clock or a content-length ends them."*

What differs is exactly that ending, and it is the one thing each section
supplies: a download's progress is bytes out of a known total (or unknown,
which is a real state and not zero), a recording's is wall-clock through its
window. Both arrive here as a fraction.

Every state is a WORD, never a colour on its own — a paused download and a
failed one must be tellable apart by someone who cannot distinguish the two
fills.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from metatv.gui.chip_row import CHIP_ACTION, build_chip_row, sidebar_meta_line
from metatv.gui.progress_paint import ProgressBar

#: Item-data roles for both transfer lists.
ROLE_ITEM_ID = Qt.ItemDataRole.UserRole          # download_id / recording_id
ROLE_CHANNEL_ID = Qt.ItemDataRole.UserRole + 1   # the channel it came from
ROLE_STATE = Qt.ItemDataRole.UserRole + 2        # the raw state string
ROLE_DEST_PATH = Qt.ItemDataRole.UserRole + 3    # the file on disk, for "reveal"

#: The bar in a transfer row, matching the Watch Alerts rail exactly so the two
#: sections read as one sidebar rather than two.
_BAR_W, _BAR_H = 44, 8


def human_bytes(n: "int | None") -> str:
    """``1234567`` -> ``"1.2 MB"``. Empty string for None, so a caller can skip it.

    Decimal units, because that is what a provider's Content-Length means and
    what a file manager will show next to the same file — matching the disk is
    worth more here than binary precision.
    """
    if n is None:
        return ""
    step = 1000.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} TB"


def add_transfer_row(
    lst,
    *,
    item_id: str,
    channel_id: str,
    title: str,
    state: str,
    state_word: str,
    fraction: "float | None",
    meta_parts: "tuple[str, ...]" = (),
    dest_path: str = "",
    tooltip: str = "",
    density: str = "",
) -> QListWidgetItem:
    """Append one transfer row to *lst* and return its item.

    Args:
        lst: The ``QListWidget`` to append to.
        item_id: download_id / recording_id — what an action needs to name it.
        channel_id: The channel behind it, so a row can open details.
        title: Display title (programme title for a recording, channel name
            for a download).
        state: Raw state string, stored for a context menu to branch on.
        state_word: The state as the user reads it. Always present, because a
            fill colour alone does not survive someone who cannot see it.
        fraction: 0.0-1.0, or ``None`` when the total is genuinely unknown —
            which draws NO bar rather than one frozen at the left edge, since
            an empty bar reads as broken rather than as unknown.
        meta_parts: Second-line fragments, joined through the shared
            ``sidebar_meta_line`` so the separator is not re-chosen here.
        dest_path: The file on disk, for a "reveal" action.
        tooltip: Row tooltip — the exact figures the row itself has no width for.
        density: Passed through to ``build_chip_row``; empty means its default.
    """
    item = QListWidgetItem()
    item.setData(ROLE_ITEM_ID, item_id)
    item.setData(ROLE_CHANNEL_ID, channel_id)
    item.setData(ROLE_STATE, state)
    item.setData(ROLE_DEST_PATH, dest_path)

    bar = None
    if fraction is not None:
        bar = ProgressBar(max(0.0, min(1.0, fraction)) * 100.0,
                          width=_BAR_W, height=_BAR_H)
        if tooltip:
            bar.setToolTip(tooltip)

    kwargs = {
        "title": title,
        "title_chips": ((CHIP_ACTION, state_word),) if state_word else (),
        "meta": sidebar_meta_line(*meta_parts) if meta_parts else "",
        "tail_widget": bar,
    }
    if density:
        kwargs["density"] = density
    row = build_chip_row(**kwargs)
    if tooltip:
        row.setToolTip(tooltip)

    lst.addItem(item)
    item.setSizeHint(row.sizeHint())
    lst.setItemWidget(item, row)
    return item
