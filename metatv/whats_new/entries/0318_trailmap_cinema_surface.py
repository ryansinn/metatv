"""What's New entry: the Explore trail-map is legible in the Daylight theme —
same fixed-dark-panel fix the preview overlay got — plus the theme drift guard
now catches every shape of the stale-stylesheet bug, not just one."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=318,
    title="Explore is readable in the Daylight theme",
    items=(
        "The Explore trail-map is a dark panel in every theme, but most of its "
        "colours were being chosen for the theme's own background. On Daylight "
        "that broke it: the \"here\" tag marking where you are in the trail was "
        "white on white and completely invisible, the watched and "
        "partly-watched badges were invisible too, the header link was "
        "unreadable, and the thumbnail and poster wells rendered as white "
        "boxes on the dark panel.",
        "It now uses the same fixed set of panel colours the preview overlay "
        "got, so Explore looks the same in all three themes. This matters "
        "together with that fix, because the preview's Explore button opens "
        "straight into this view — repairing one and not the other just moved "
        "where you'd meet the problem.",
        "Behind that: the check that stops styling from going stale when you "
        "switch themes only recognised one way of writing the mistake. Eleven "
        "real cases were written differently and slipped past it — including "
        "the pill buttons in the Recipe bar, the source buttons in the "
        "sidebar, the Explore row highlight, and the pass/fail buttons in the "
        "dev QA window, all of which kept their old colours after a theme "
        "switch. All eleven are fixed, and the check now recognises the "
        "mistake whatever shape it is written in.",
    ),
    version="0.32.0",
    date="2026-08-21",
    test_steps=(
        "Switch to the Daylight theme (Style menu), open a movie's details "
        "pane, raise the preview overlay from a Similar Titles row, then click "
        "Explore — the trail-map opens with a dark panel, readable titles, and "
        "no white boxes where the thumbnails belong.",
        "In that Explore view, look at the last stop on your trail — the "
        "\"here\" tag beside it is a light chip with dark text, not blank "
        "space. Compare against Midnight: they should look the same.",
        "Find a row you've watched and one you're part-way through — the "
        "watched tick and the partial-watch badge are both visible on the dark "
        "panel in Daylight.",
        "Open the Recipe view, switch the theme while it is open, and check "
        "the Recipe/Saved pill buttons — the selected pill picks up the new "
        "theme instead of keeping its old colours.",
        "With the sidebar open, switch themes and check the Sources strip's "
        "Refresh-All and Add buttons, and the Watch Alerts add button — they "
        "restyle too.",
    ),
)
