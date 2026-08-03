"""What's New entry: a Layout menu for panel visibility, plus the panel-shrink
bug it uncovered."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=288,
    title="A Layout menu for the panels — and panels stop shrinking",
    items=(
        "New Layout menu: show or hide the sidebar, the details pane and the "
        "filter panel without hunting for a splitter handle. Each remembers "
        "its width.",
        "The filter-panel toggle moved here from Style. Style is what things "
        "look like; Layout is what is on screen — and having one of the three "
        "panels controlled from a different menu than the other two was a trap.",
        "The ticks are read from the actual panels each time the menu opens, so "
        "dragging a panel shut by hand is reflected correctly rather than the "
        "menu insisting it is still open.",
        "Fixed while building it: a panel restored after being collapsed came "
        "back narrower than it was — a 416px sidebar returned as 327px, losing "
        "a little more on every collapse. The space taken by the neighbouring "
        "panels was never given back. This affected the splitter handles too, "
        "so it was already happening before this menu existed.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open the Layout menu. It lists Sidebar, Details pane and Filter panel, "
        "each ticked to match what is currently on screen.",
        "Untick Sidebar — it disappears completely (not merely narrower). Tick "
        "it again: it returns at the same width it had before.",
        "Collapse and restore the sidebar five times in a row. It must be the "
        "same width at the end as at the start, not progressively narrower.",
        "Do the same with Details pane, and confirm hiding one does not affect "
        "the other.",
        "Drag the sidebar's splitter handle shut by hand, then open the Layout "
        "menu — Sidebar shows as unticked.",
        "Toggle Filter panel from Layout and confirm it works both directions; "
        "confirm it is no longer listed in the Style menu.",
        "Restart the app and confirm the panel widths you left are restored.",
    ),
)
