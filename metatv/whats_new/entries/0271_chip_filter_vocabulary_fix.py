"""What's New entry for the row-chip filter fix: chips filtered on the code they
displayed rather than the value the tag table stores, so quality and language
chips emptied the list. Also rounds the row chips to match the sidebar pills."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=271,
    title="Clicking a quality or language chip no longer empties the list",
    items=(
        "Row chips became clickable in the last build, but two of them filtered "
        "on the wrong thing and returned nothing at all: a quality chip searched "
        "for \"4K\" when the stored value is \"4K / UHD\", and a language chip "
        "searched for \"EN\" when the stored value is \"English\".",
        "Region and genre chips were unaffected, because for those the label and "
        "the stored value happen to be identical — which is exactly why the "
        "problem wasn't obvious.",
        "Collection chips didn't filter correctly either: they used whichever "
        "row was selected rather than the chip you clicked. They now use the "
        "clicked chip.",
        "If a chip ever has no matching stored value, it now does nothing "
        "instead of returning an empty list that looks like a broken filter.",
        "Row chips are also properly rounded now, matching the pill shape used "
        "in the sidebar, rather than the squared-off boxes they were.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Click a 4K (or UHD) quality chip in the results list — the list "
        "narrows to 4K titles instead of going empty, and the filter chip in "
        "the search area reads \"Quality: 4K / UHD\".",
        "Click an EN language chip — results narrow to English titles, with a "
        "\"Language: English\" filter chip.",
        "Click a region chip (US, FR) — still works exactly as before.",
        "Click a collection chip on a row that is NOT selected — the results "
        "filter to that collection, not to the collection of whichever row was "
        "selected beforehand.",
        "Look at the chips themselves: they are rounded pills, the same shape "
        "as the language chips in the sidebar, not square-cornered boxes.",
    ),
)
