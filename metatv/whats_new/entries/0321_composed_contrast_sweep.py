"""What's New entry: swept the stylesheets built inside widget files — which no
contrast check had ever measured — and fixed five unreadable controls, one of
them invisible in every theme."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=321,
    title="Five unreadable controls across Discover, filters and dialogs",
    items=(
        "The \"Clear\" button in the filter bar was drawn in a colour meant "
        "for separator lines, on a background that resolves to the same value "
        "— text and button identical, in every theme. It has been invisible "
        "the whole time.",
        "The \"Watch\" button in the new-content alert dialog used body text "
        "on a solid blue fill, unreadable in Daylight. The category label on "
        "Discover posters used a colour that is dark navy in Daylight, on a "
        "dark poster scrim. The mood pills in the category picker, and the "
        "\"No poster available\" placeholder, were similarly washed out.",
        "All five are fixed, and the filter bar's three controls (two "
        "dropdowns and Clear) now share one style instead of three copies of "
        "the same one.",
        "Why nobody had caught them: the contrast checks only measured styles "
        "defined in the central theme file, and these are built inside the "
        "widgets themselves — roughly 280 of them, none ever measured. Those "
        "are now swept automatically in all three themes, so this class of "
        "bug gets caught before it ships rather than by looking.",
    ),
    version="0.32.0",
    date="2026-08-22",
    test_steps=(
        "Open the filter panel and find the \"Clear\" button — it now looks "
        "like the \"▼\" dropdowns beside it, with readable text; before this "
        "it was a blank-looking box.",
        "Switch to Daylight (Style menu) and open Discover — the category "
        "label in the corner of each poster is readable against the poster.",
        "Still in Daylight, open a title with no poster in the details pane — "
        "\"No poster available\" is legible in the empty frame.",
        "Trigger a new-content alert dialog (Watch Alerts → add a keyword that "
        "matches) and check the \"Watch\" button reads clearly in every theme.",
        "Right-click a channel → Category → open the mood picker; the "
        "unselected mood pills are readable rather than washed out.",
    ),
)
