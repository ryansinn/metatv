"""What's New entry: removing one sidebar row rebuilt the entire section."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=292,
    title="Removing one thing no longer rebuilds the whole list",
    items=(
        "Unqueuing a title, un-favoriting one, or marking a recommendation "
        "\"not interested\" used to re-read the entire section from the "
        "database and rebuild every row in it. On a 600-item Watch Queue that "
        "is 600 rows torn down and remade to delete one.",
        "Those actions now just take that one row out. The rest of the list is "
        "left exactly as it was — same rows, same scroll position, no flicker.",
        "Group headers keep up: \"Never Watched (560)\" becomes (559), and a "
        "group whose last item you removed loses its header instead of standing "
        "over nothing.",
        "Unqueuing a series no longer disturbs episodes of it you queued "
        "separately, and vice versa — they are independent entries.",
        "Adding something still does a full refresh, because a new row has to "
        "be placed in the right group in the right order.",
    ),
    version="0.26.0",
    date="2026-08-04",
    test_steps=(
        "Open the Watch Queue and scroll well down into it.",
        "Right-click a row and remove it from the queue. Only that row "
        "disappears — the list does not flash, rebuild, or move you.",
        "Check the \"Never Watched\" header: its count dropped by exactly one.",
        "Remove the last remaining item of a group (e.g. the only Continue "
        "Watching entry). That group's header disappears with it.",
        "Queue a series, then queue one of its episodes. Unqueue the series — "
        "the episode entry is still there.",
        "Open the 🔍 filter, type something, then remove one visible row. The "
        "filter stays applied and its \"(N of M)\" count updates.",
        "In Favorites, un-favorite one item — same behaviour: one row leaves.",
        "In Recommended, right-click a row and choose \"Not interested\". That "
        "row goes and the others stay put.",
        "Add something to the queue and confirm it still appears in the right "
        "group (a full refresh is expected there).",
    ),
)
