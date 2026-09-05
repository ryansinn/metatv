"""Whether a channel is recording or scheduled to record, for a guide row.

Catch, Keep, Record (Feature 3, settled 2026-08-30) puts a Record control on
every guide row — Watch Alerts, On Now, Browse — and each of those three
needs the SAME answer to "is THIS row's channel, in THIS row's window,
already being recorded or already scheduled?" from one
``RecordingManager.progress()`` snapshot. A pure helper (no Qt, no I/O) so it
lives in one place rather than three copies of the same overlap test, one per
surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from metatv.core.epg_utils import now_utc, to_local
from metatv.gui import icons

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.recording_manager import RecordingProgress

#: Copy for a programme row that is neither recording nor scheduled — the
#: plain "you could record this" affordance.
RECORD_TOOLTIP = (
    "Record this programme — schedules its guide window with your padding"
)

#: States a match may carry that count as "already claimed" for this row.
_CLAIMED_STATES = ("recording", "scheduled")


def indicator_for(
    channel_id: "str | None",
    start: "datetime | None",
    stop: "datetime | None",
    progress_rows: "list[RecordingProgress]",
    now: "datetime | None" = None,
) -> "tuple[str | None, str]":
    """State + tooltip for one programme row's Rec control.

    Args:
        channel_id: The row's channel id. ``None`` (a group header, a Q3 day
            separator) never matches.
        start: The programme's guide start, UTC-naive.
        stop: The programme's guide stop, UTC-naive.
        progress_rows: A snapshot from ``RecordingManager.progress()`` — pass
            the SAME list to every row refreshed in one pass, so the overlap
            set is computed once per tick/populate rather than once per row.
        now: The instant to break ties by, UTC-naive; defaults to
            ``now_utc()``. Only matters when a channel somehow carries more
            than one scheduled match for this window — picks whichever is
            actually current over whichever merely comes first.

    Returns:
        ``("recording", tooltip)`` when a recording for this channel overlaps
        the window, ``("scheduled", tooltip)`` when only a not-yet-started one
        does, else ``(None, RECORD_TOOLTIP)``. Overlap is the standard
        half-open-interval test — inclusive at each interval's start,
        exclusive at its end — so a recording that ends exactly when this
        programme starts does not flag it, and vice versa.
    """
    if not channel_id or start is None or stop is None:
        return None, RECORD_TOOLTIP

    matches = [
        r for r in progress_rows
        if r.channel_id == channel_id and r.state in _CLAIMED_STATES
        and start < r.ends_at and r.starts_at < stop
    ]
    if not matches:
        return None, RECORD_TOOLTIP

    recording = next((r for r in matches if r.state == "recording"), None)
    if recording is not None:
        return "recording", f"Recording — ends {to_local(recording.ends_at):%H:%M}"

    now = now or now_utc()
    # Prefer whichever scheduled match's OWN window contains `now` (the
    # imminent one) over whichever merely sorts first — relevant only when a
    # channel somehow carries more than one scheduled match for this row.
    current = next(
        (r for r in matches if r.starts_at <= now < r.ends_at), matches[0]
    )
    return "scheduled", (
        f"Scheduled — {to_local(current.starts_at):%H:%M}"
        f"–{to_local(current.ends_at):%H:%M}"
    )


def glyph_for(state: "str | None") -> str:
    """Which ``icons.py`` glyph a Rec cell shows for `state` (plain-text glyphs,
    for a tree cell — the sidebar row's vector icon uses its own key, one of
    ``"record"``/``"recording_active"``/``"recording_scheduled"``)."""
    if state == "recording":
        return icons.recording_active_icon
    if state == "scheduled":
        return icons.recording_scheduled_icon
    return icons.record_icon


def vector_key_for(state: "str | None") -> str:
    """Which ``icons.VECTOR_KEYS`` role the sidebar's pixmap-rendered Record
    control uses for `state` — the ``_AlertRow`` sibling of :func:`glyph_for`."""
    if state == "recording":
        return "recording_active"
    if state == "scheduled":
        return "recording_scheduled"
    return "record"
