"""What's New entry for row chips gaining hover explanations and click-to-filter."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=270,
    title="Chips in the results list now explain themselves — and filter when you click",
    items=(
        "The little coloured labels on each result (4K, EN, US, a genre, a "
        "collection) looked like buttons but did nothing at all: no hover, no "
        "click, not even a cursor change.",
        "Hovering one now explains what it is — \"Picture quality: 4K\", "
        "\"Region: United States (US)\", \"Genre: Drama\" — so the colour "
        "coding stops being something you have to memorise.",
        "Clicking one filters the results to just that value, using the same "
        "filter chip that appears when you click metadata in the details pane. "
        "Clicking a chip only filters — it does not change which row is "
        "selected, so it can't interfere with double-clicking to play.",
        "Chips that can't filter don't pretend they can. The year and the "
        "\"×N\" versions badge explain themselves on hover but show no "
        "clickable cursor, because there is nothing to filter them by.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Hover a quality chip (4K/UHD) in the results list — the cursor becomes "
        "a pointing hand and a tooltip names the quality.",
        "Hover the year on the same row — a tooltip appears but the cursor "
        "stays an arrow, because year is not filterable.",
        "Click a language or region chip — the results narrow to that value and "
        "a filter chip appears in the search area, exactly as a details-pane "
        "metadata click does. Dismiss it to restore the full list.",
        "Click a chip on a row that is NOT currently selected — the filter "
        "applies and the selection does not jump to that row.",
        "Click a genre chip on a movie — results narrow to that genre.",
        "Scroll the list a long way, then hover chips again — tooltips still "
        "match the chip under the cursor (the hit areas follow the repaint).",
    ),
)
