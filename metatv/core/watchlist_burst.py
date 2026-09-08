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

    Takes ``(title, channel_name, time_str)`` per match and counts DISTINCT
    titles — several channels carrying one programme are one show — returning
    ``(banner_title, banner_message, auto_dismiss_ms)``. Rationale and the
    owner's log: tests/test_watchlist_burst_notification.py.
    """
    # Collapse by TITLE first. One programme carried by several channels is one
    # thing starting, not several: the owner's banner read "Two and a Half Men,
    # Two and a Half Men, Two and a Half Men and 11 more", spending every named
    # slot on one show and hiding the rest. Insertion order is kept, so the
    # earliest match still leads.
    by_title: "dict[str, list[tuple[str, str, str]]]" = {}
    for match in pending:
        by_title.setdefault(match[0], []).append(match)
    titles = list(by_title)

    if len(titles) == 1:
        title = titles[0]
        matches = by_title[title]
        _t, channel_name, time_str = matches[0]
        others = len(matches) - 1
        where = ("On " + channel_name if not others
                 else f"On {channel_name} and {others} other channel"
                      f"{'s' if others > 1 else ''}")
        return (f"Starting {time_str}: {title}", where, SINGLE_DISMISS_MS)

    # Say the time only when every programme agrees on it. A tick CAN catch a
    # spread — the first sweep, or a resume from sleep — and naming one time
    # there would be confidently wrong about the rest.
    times = {t for _title, _chan, t in pending}
    when = f" {times.pop()}" if len(times) == 1 else ""

    named = titles[:BURST_NAMED_LIMIT]
    rest = len(titles) - len(named)
    listed = ", ".join(named) + (f" and {rest} more" if rest else "")
    return (f"{len(titles)} shows starting{when}", listed, BURST_DISMISS_MS)
