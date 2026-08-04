"""What's New entry: Recommended threw you back to the top on every refresh."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=290,
    title="Recommended stays where you left it",
    items=(
        "Scrolling deep into Recommended and then doing anything that reloads "
        "the list — refreshing it, or choosing \"Show N versions separately\" on "
        "a row — bounced you back to the first row. The title you had just "
        "found was then somewhere above you again.",
        "The list now keeps your position across a reload, so acting on a row "
        "leaves you looking at that row.",
        "The Watch Queue, Favorites and History sections were fixed for this "
        "previously; Recommended was built slightly differently and had been "
        "missed. All four now share one piece of code, so it can't happen to "
        "one of them again.",
        "When there is nothing to show — no ratings yet, or a load failure — "
        "the message stays visible at the top rather than being scrolled past.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open the sidebar's Recommended section and make it tall enough to "
        "scroll (drag the section divider), then scroll down into the middle "
        "of the list.",
        "Click the refresh button in the Recommended header. The list reloads "
        "and you are still scrolled to the same place, not back at row 1.",
        "Scroll down again, right-click a row showing \"N versions grouped\" and "
        "choose \"Show N versions separately\". The list reloads and keeps your "
        "position; the versions are now listed separately.",
        "Scroll to the very bottom and refresh — you stay at the bottom, and "
        "the list is not blank.",
        "Scroll to the top and refresh — you stay at the top (no surprise "
        "jump downward).",
    ),
)
