"""What's New entry for the selection-highlight contrast fix (the selected-row
text color read from the on-background text ramp instead of an on-accent token,
which made Daylight's selection unreadable and both dark themes hard to read)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=265,
    title="Selected rows are legible in every theme",
    items=(
        "The highlight color for a selected item took its text color from "
        "the theme's brightest on-background text. That is the right color "
        "for text sitting ON the app background, but the selection is a "
        "solid accent-colored fill — a different surface entirely.",
        "In Daylight the result was near-black text on a dark navy "
        "selection: about 1.2:1 contrast, effectively unreadable. Midnight "
        "and Graphite were milder but still poor (roughly 2:1), because "
        "their accent is a light blue and the text on it was white.",
        "Selection text now comes from a dedicated per-theme color chosen "
        "to sit on the accent fill, and clears the 4.5:1 readability bar in "
        "all three themes. Note this changes how a selected row looks in "
        "Midnight and Graphite — dark text on the blue fill instead of "
        "white.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Settings -> Interface -> Appearance -> Daylight. Open any dropdown "
        "with several entries (e.g. the Settings theme selector itself) and "
        "hover/arrow through it — the highlighted entry's text is clearly "
        "readable against the blue highlight, not near-invisible dark-on-dark.",
        "Still in Daylight, click into a text field (e.g. the channel search "
        "box), type a few characters and select them — the selected text "
        "stays readable against the selection fill.",
        "Switch to Midnight, repeat the dropdown check — the highlighted "
        "entry now shows dark text on the blue fill and is easier to read "
        "than the previous white-on-blue.",
        "Switch to Graphite and repeat once more — same result, legible "
        "highlighted entry.",
    ),
)
