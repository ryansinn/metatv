"""What's New entry: episodes can now be resumed from where you left off."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=304,
    title="Episodes can now be resumed",
    items=(
        "Selecting an episode you'd already started watching now shows a "
        "Resume M:SS button next to Play Episode, matching how movies already "
        "worked. Previously an episode's details only ever offered "
        "\"Play Episode\" — even with a saved position — so resuming meant "
        "starting over from the beginning.",
        "Clicking Resume starts that episode from its own saved position, not "
        "the series'. Play Episode still starts from the beginning.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Start playing an episode of a series, stop partway through so a "
        "position is saved, then reopen that same episode in the details "
        "pane — a Resume M:SS button appears next to Play Episode, showing "
        "the correct saved time.",
        "Click Resume on that episode — playback starts from the saved "
        "position, not from the beginning.",
        "Open an episode you've never watched (or one already marked "
        "watched) — no Resume button appears, only Play Episode.",
        "Select a season header or the series root after viewing an episode "
        "with Resume showing — the Resume button disappears (series roots "
        "never show it).",
    ),
)
