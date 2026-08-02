"""What's New entry for lightbox breadcrumb trail feature."""
from __future__ import annotations

from metatv.whats_new.entry import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=243,
    title="Lightbox Breadcrumb Trail",
    description=(
        "When you dive deep into Similar Titles (A → B → C → D), "
        "a subtle breadcrumb trail now shows your path at the top of the lightbox. "
        "Click any earlier crumb to jump back to that point; long trails elide in the middle "
        "with a clickable '…' that opens the full Explore trail-map."
    ),
    version="0.21.0",
    date="2026-08-02",
    test_steps=(
        (
            "Open a channel's Similar Titles preview.",
            "You see a subtle 'Origin › A › B › Current' breadcrumb "
            "inside the lightbox header when you dive into similar titles.",
        ),
        (
            "Click on an earlier crumb (e.g., 'A' in the trail).",
            "The lightbox jumps back to that title, truncating the trail. "
            "The current crumb is not clickable.",
        ),
        (
            "Dive 5+ levels deep (A → B → C → D → E).",
            "The trail elides in the middle: 'Origin › … › D › Current'. "
            "Click the '…' to open the Explore view showing the full path.",
        ),
        (
            "Hover over a crumb.",
            "Its full title appears as a tooltip (crumbs are elided to fit).",
        ),
    ),
)
