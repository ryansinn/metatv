"""What's New entry: a standalone Buffer menu, and the filter-panel toggle that
could only ever turn off."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=280,
    title="Buffer menu, and the filter panel can be turned back on",
    items=(
        "The filter panel could be hidden but not brought back, and hiding it "
        "only made it narrower rather than removing it. It has a minimum width, "
        "so the collapse could never actually reach zero — and because the code "
        "worked out which way to toggle by measuring that width, it decided the "
        "panel was still open and hid it again every time.",
        "It now hides properly, comes back with one click, and returns to the "
        "width you had it at rather than a default.",
        "New Buffer menu in the menu bar: Reconnect only, Modest, Large, or "
        "Open-ended — the same choices as Settings, reachable while a stream is "
        "misbehaving instead of several clicks away.",
        "Changing the buffer applies to the next stream you start; it will not "
        "interrupt what is currently playing.",
        "Buffer is its own menu rather than part of Style on purpose: Style is "
        "about how things look, and this has no visual effect at all.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Style → Filter panel: untick it. The panel disappears completely — not "
        "just narrower.",
        "Tick it again: it comes back, at the width you had it, not a default. "
        "Repeat several times — it keeps working.",
        "Drag the filter panel to a distinctly different width, hide it, show "
        "it: it returns to your width.",
        "Open the Buffer menu — the profile currently in use is ticked, and "
        "hovering any entry says it applies to the next stream.",
        "Pick a different buffer profile while something is playing: playback "
        "continues uninterrupted and the status bar confirms it is saved.",
        "Open Settings → Playback: the buffer dropdown matches what you chose "
        "in the menu.",
    ),
)
