"""What's New entry: unreadable view chips, Daylight's invisible list boundary,
and Graphite being a near-copy of Midnight."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=296,
    title="The view chips were unreadable, and Graphite was barely a second theme",
    items=(
        "The primary view chips — Search, EPG, Recommended, Discover, Recipe — "
        "were unreadable in both states on both dark themes. The selected chip "
        "wrote white text on a near-white lavender: 1.31:1, where 4.5:1 is the "
        "floor. The resting chips sat on one of the fixed-light chip surfaces, "
        "a pale slab in a dark app, at 2.30:1.",
        "The cause was a hardcoded colour. A literal cannot follow a palette, "
        "so the chip kept writing white while the fill beneath it drifted from "
        "a dark blue to an almost-white lavender. It now uses the token whose "
        "whole job is \"legible on a solid accent\" (6.75:1 in Midnight), and a "
        "real surface at rest.",
        "Those chips also now follow a live theme switch instead of keeping the "
        "old theme's colours until restart.",
        "Daylight had no visible boundary between the app and its lists — "
        "chrome and content were one undifferentiated white field at 1.02:1. "
        "The chrome is now a step greyer, so the lists read as white panels "
        "sitting on it.",
        "Graphite was described as the lighter, fully neutral dark theme but "
        "had converged to within two points of Midnight at every surface "
        "(#111111 against #111113) — the same defect that was fixed once "
        "before and came back when themes were rebuilt from colour scales. Its "
        "whole surface ramp is a step lighter again, so the two dark themes "
        "look like two themes.",
    ),
    version="0.27.0",
    date="2026-08-04",
    test_steps=(
        "Look at the view chips along the bottom (Search / EPG / Recommended / "
        "Discover / Recipe). The selected one's label is clearly readable on "
        "its fill, and the unselected ones read as buttons rather than pale "
        "slabs.",
        "Click through to EPG, then Discover. The newly-selected chip is "
        "legible each time, and the one you left returns to a resting style.",
        "Check the Search bar's own All / Hidden chips — same fix, same "
        "widget.",
        "Switch to Daylight (Settings → Interface → Theme). The channel list "
        "and the filter panel read as white surfaces on a greyer app "
        "background — you should be able to see where each panel ends.",
        "Switch to Graphite. It should now read as noticeably lighter than "
        "Midnight rather than the same theme with a different accent; flip "
        "between the two to compare.",
        "While on Graphite, switch straight to Daylight and back without "
        "restarting. The view chips re-colour with everything else.",
    ),
)
