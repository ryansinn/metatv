"""What's New entry: find-in-queue, for a Watch Queue with hundreds of entries."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=291,
    title="Find something in a 600-item Watch Queue",
    items=(
        "The Watch Queue's header has a 🔍 button. Click it and a filter box "
        "appears, focused and ready to type: any part of a title — or a "
        "year — narrows the list to what matches. Click it again (or press "
        "Escape) and the box goes away, giving its space back to the list.",
        "Hiding the box always clears the filter, so the queue is never quietly "
        "showing you a fraction of itself with nothing on screen to explain it.",
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
        "Open the Watch Queue in the sidebar. There is NO filter box taking up "
        "space — just a 🔍 button in the section's title bar.",
        "Click 🔍. The box appears already focused, so you can type "
        "immediately.",
        "Type part of a title you know you queued. Only matching rows remain, "
        "and headers of groups with no matches disappear entirely.",
        "Check a remaining header — it reads \"(N of M)\", where M is the "
        "group's full size.",
        "Type something that matches nothing. The list says so instead of "
        "going blank.",
        "Click the box's clear (×) button. Every row comes back and the "
        "headers show their original counts again.",
        "Type a filter, then click 🔍 again (or press Escape). The box goes "
        "away AND every row comes back — a filter is never left applied behind "
        "a hidden box.",
        "Reopen the app: the box is where you left it (shown or hidden), but "
        "always empty.",
        "Type a filter, then right-click a visible row and mark it watched. "
        "The list refreshes and your filter is still applied.",
        "Type a four-digit year (e.g. 1999) and confirm titles from that year "
        "are found.",
        "Restart the app and confirm the Watch Queue opens unfiltered.",
    ),
)
