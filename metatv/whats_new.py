"""What's New changelog — one entry per user-facing release.

Append a new ``WhatsNewEntry`` (next ``id``) here whenever a user-facing change
lands. The in-app What's New dialog reads this list to show users what changed
since their last launch.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WhatsNewEntry:
    id: int                  # monotonic; the "seen" cursor. Each new entry = previous max + 1.
    version: str             # display only, e.g. "0.1.0"
    date: str                # ISO "YYYY-MM-DD"
    title: str
    items: tuple[str, ...]   # user-facing bullet points (frozen dataclass → tuple, not list)


WHATS_NEW: list[WhatsNewEntry] = [
    WhatsNewEntry(
        id=1,
        version="0.1.0",
        date="2026-06-19",
        title="A more reliable player",
        items=(
            "Streams now auto-reconnect after brief network drops instead of dying.",
            "Pick how much to buffer in Settings → Playback (reconnect-only, modest, or large).",
            "New optional 'pre-buffer before playing' — fills the buffer first for stutter-free movie starts.",
            "Diagnose a troublesome stream and apply its recommended tuning in one click.",
        ),
    ),
    WhatsNewEntry(
        id=2,
        version="0.1.0",
        date="2026-06-19",
        title="Split Streams — watch more than one source at once",
        items=(
            "Turn on 'Split' (bottom bar or Settings → Playback) to give each source its own player window.",
            "Right-click any channel → 'Play in New Window' to open a second stream without disturbing the first.",
            "The playback-health readout shows your latest window; click it to cycle through the others.",
        ),
    ),
    WhatsNewEntry(
        id=3,
        version="0.1.0",
        date="2026-06-19",
        title="Consistent right-click menus everywhere",
        items=(
            "Every channel list — sidebar, history, favorites, recommendations, EPG — now offers the same core actions (Play, Favorite, Queue, rate).",
            "'Play in New Window' is available from every list.",
            "The EPG 'On Now' list gained Play / Favorite / Queue, which it lacked before.",
        ),
    ),
    WhatsNewEntry(
        id=4,
        version="0.1.0",
        date="2026-06-19",
        title="EPG improvements",
        items=(
            "'On Now' now shows channels from your active sources only — no more entries from disabled ones.",
            "Channel categories load instantly (no more stuck 'Loading categories…' on live channels).",
            "'On Now' columns remember the order you arrange them in.",
            "EPG Discover: '+ Channel' adds the channel to My Channels, plus a Play button and an expandable list of upcoming matches.",
        ),
    ),
]


def latest_id() -> int:
    """Return the highest entry id in the changelog, or 0 if empty."""
    return max((e.id for e in WHATS_NEW), default=0)


def entries_since(last_seen_id: int) -> list[WhatsNewEntry]:
    """Return entries newer than last_seen_id, newest first."""
    return sorted(
        (e for e in WHATS_NEW if e.id > last_seen_id),
        key=lambda e: e.id,
        reverse=True,
    )
