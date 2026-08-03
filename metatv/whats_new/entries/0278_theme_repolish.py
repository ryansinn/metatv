"""What's New entry: list backgrounds now follow a live theme switch."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=278,
    title="List backgrounds follow the theme without restarting",
    items=(
        "After switching theme, the lists kept the old background — dark panels "
        "under light chrome in Daylight, and light panels under dark chrome "
        "going the other way. Restarting always looked right, which was the "
        "clue: at startup the theme is applied before anything is drawn, so "
        "everything is built with the correct colours from the start.",
        "Switching while running updated the colours the app knows about but "
        "never told the existing lists to repaint themselves. They now get told.",
        "View → Refresh reloads content, not colours — it was never going to "
        "help here.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "With the app running in Midnight, switch to Daylight. The channel "
        "list, sidebar lists and Watch Queue all take the light background "
        "immediately — no restart.",
        "Switch back to Midnight. They go dark again (the failure was "
        "symmetric, so both directions need checking).",
        "Switch to Graphite and back to Daylight — still correct.",
        "Restart in each theme and confirm nothing regressed at startup.",
    ),
)
