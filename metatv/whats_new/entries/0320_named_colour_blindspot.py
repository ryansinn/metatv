"""What's New entry: hardcoded colour names ("white", "gray") replaced with
theme colours — fixes invisible badges on the results rows in Daylight, and
unreadable badges/buttons in the dark themes."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=320,
    title="Badges and buttons that were unreadable in one theme or another",
    items=(
        "The language, platform and audio badges on every results row had "
        "their text nailed to white, while their background follows the "
        "theme. In Daylight that meant white text on a near-white badge — "
        "invisible, on the most-used surface in the app. They now use the "
        "theme's own text colour, which flips with the theme like the badge "
        "does.",
        "The same hardcoded white made the PPV quality/sport badges and the "
        "Play buttons on PPV and the TV-guide watchlist hard to read in "
        "Midnight and Graphite, where those buttons are filled with bright "
        "mint and orange. Text on a coloured fill is now chosen by measuring "
        "against that fill, so it stays readable whichever colour the fill "
        "turns out to be.",
        "The multi-select filter dropdowns (\"Genres ▼\") were a hard-white "
        "slab in every theme, lettered in a colour meant for separator lines. "
        "Both copies now share one themed style.",
        "Why these survived every previous sweep: the check that hunts stray "
        "colours only looked for hex codes like #ffffff, so the word \"white\" "
        "was invisible to it. It now catches colour names too, and the row "
        "badges are measured for contrast in all three themes.",
    ),
    version="0.32.0",
    date="2026-08-22",
    test_steps=(
        "Switch to the Daylight theme (Style menu) and look at the results "
        "list — the language/region, platform and audio badges on each row are "
        "readable, not blank-looking chips.",
        "Switch to Midnight and check the same badges — still readable; the "
        "text should flip colour between the two themes.",
        "Open a PPV event (Discover → PPV, if you have PPV content) in "
        "Midnight — the quality and sport badges and the ▶ Play button all "
        "have readable text on their coloured fills.",
        "Open the TV guide watchlist and find a programme with a Play button — "
        "its label is readable on the green fill in every theme.",
        "Open any filter bar with a \"▼\" multi-select dropdown in a dark "
        "theme — the button matches the rest of the app instead of being a "
        "white block.",
    ),
)
