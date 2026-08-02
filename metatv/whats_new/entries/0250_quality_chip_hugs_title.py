"""What's New entry for the quality-chip position fix in list rows."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=250,
    title="Quality chip now sits next to the title",
    items=(
        "In list and search results, the quality chip (4K / FHD / HD) now sits "
        "immediately after the title with a single space, left-aligned with it "
        "— instead of drifting to the far right of the row against the year and "
        "language chips.",
        "The right-hand group is unchanged: year stays plain text, then region, "
        "subtitle marker, and language chips flush right, with the channel's own "
        "language furthest right.",
    ),
    version="0.22.0",
    date="2026-08-02",
    test_steps=(
        "Search for a title you own in 4K (or open Browse) — the 4K chip appears "
        "immediately to the right of the title text, not at the far right edge.",
        "Widen the window — the chip stays beside the title instead of sliding "
        "right with the window edge.",
        "Check a row with a long, truncated title — the chip still sits directly "
        "after the ellipsis, never overlapping the year.",
        "Settings → Interface → Channel List → switch density between Compact "
        "and Comfy — the chip hugs the title in both.",
        "Confirm the year is still plain text (not a chip) and right-aligned.",
    ),
)
