"""What's New entry: find-in-queue, for a Watch Queue with hundreds of entries."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=291,
    title="Find something in a 600-item Watch Queue",
    items=(
        "The Watch Queue has a filter box at the top. Type any part of a "
        "title — or a year — and the list narrows to what matches.",
        "Each group header shows what it is currently showing, e.g. \"Never "
        "Watched (12 of 597)\", so a filtered list never misstates its size.",
        "Nothing is hidden permanently and nothing is deleted: clearing the "
        "box brings the whole queue straight back. The filter is not "
        "remembered between launches, so the queue always opens complete.",
        "Filtering survives acting on a row — marking something watched no "
        "longer dumps all several hundred entries back on you mid-sort.",
        "Titles are matched on both the cleaned name and the name your "
        "provider used, since those can differ and you may remember either.",
        "Deliberately NOT added: automatic archiving of old queue items. "
        "Measured against a real 612-entry queue, nothing in it was older than "
        "three months, so an age cutoff would either archive nothing or hide "
        "hundreds of things you had chosen on purpose.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open the Watch Queue in the sidebar. There is a \"Find in queue…\" box "
        "above the list.",
        "Type part of a title you know you queued. Only matching rows remain, "
        "and headers of groups with no matches disappear entirely.",
        "Check a remaining header — it reads \"(N of M)\", where M is the "
        "group's full size.",
        "Type something that matches nothing. The list says so instead of "
        "going blank.",
        "Click the box's clear (×) button. Every row comes back and the "
        "headers show their original counts again.",
        "Type a filter, then right-click a visible row and mark it watched. "
        "The list refreshes and your filter is still applied.",
        "Type a four-digit year (e.g. 1999) and confirm titles from that year "
        "are found.",
        "Restart the app and confirm the Watch Queue opens unfiltered.",
    ),
)
