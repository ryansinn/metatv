"""One banner for everything a watchlist check finds, instead of one each.

Split out of :mod:`epg_manager` for the reason ``db_lock`` and
``sidebar/section_cap`` were: this is pure text composition with no database,
no Qt and no manager state, so keeping it in a 1,359-line module made both
harder to read and forced a ratchet increase to say something a 40-line file
says better.

**The bug it fixes.** ``EpgManager`` checks every 60 seconds for programmes
starting within ``epg_notification_minutes_before`` (15 by default) and raised
one banner per match. Television starts on the half hour, so they arrive
together — the owner's idle log caught seven landing in the same second at
01:15, among singles at 00:50, 00:52, 01:13, 01:20, 01:22 and 01:30.

**Why the tick is the right unit**, and not an approximation: after the first
sweep, each tick picks up only programmes NEWLY inside the lead window, so one
batch holds things starting within about the same minute. The 01:20 and 01:22
above still arrive as two banners, which is what makes this a fix for a burst
rather than a cap on the feature.
"""

from __future__ import annotations

#: Titles named in a burst before it switches to a count — three fits the banner
#: without a third line, and past that the number is the useful part.
BURST_NAMED_LIMIT = 3

#: A burst dismisses slower than a single alert: more to read, and missing it
#: means missing several shows rather than one.
BURST_DISMISS_MS = 15_000
SINGLE_DISMISS_MS = 10_000


def burst_banner(pending: list[tuple[str, str, str]]) -> tuple[str, str, int]:
    """Compose ONE banner for everything a single 60-second tick found.

    Emitting one per programme meant seven toasts in the same second, because
    programmes cluster on the half hour and all entered the lead window on the
    same tick. The tick is the right unit to coalesce on and not by
    approximation: after the first sweep each one picks up only programmes
    NEWLY inside the window, so a ``pending`` list starts within about the same
    minute — alerts genuinely minutes apart still arrive separately.

    Takes ``(title, channel_name, time_str)`` per match, returns
    ``(banner_title, banner_message, auto_dismiss_ms)``. Rationale and the
    owner's log: tests/test_watchlist_burst_notification.py.
    """
    if len(pending) == 1:
        title, channel_name, time_str = pending[0]
        return (f"Starting {time_str}: {title}", f"On {channel_name}",
                SINGLE_DISMISS_MS)

    # Say the time only when every programme agrees on it. A tick CAN catch a
    # spread — the first sweep, or a resume from sleep — and naming one time
    # there would be confidently wrong about the rest.
    times = {t for _title, _chan, t in pending}
    when = f" {times.pop()}" if len(times) == 1 else ""

    named = [t for t, _chan, _time in pending[:BURST_NAMED_LIMIT]]
    rest = len(pending) - len(named)
    listed = ", ".join(named) + (f" and {rest} more" if rest else "")
    return (f"{len(pending)} shows starting{when}", listed, BURST_DISMISS_MS)
