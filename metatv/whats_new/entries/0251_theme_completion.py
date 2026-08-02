"""What's New entry for the Daylight/Graphite palette completion + live
theme-switch coverage fix."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=251,
    title="Daylight and Graphite themes finished; switching themes now restyles more of the app live",
    items=(
        "Daylight is now a genuine light theme: every background/surface that "
        "was still dark (the \"hidden by Global Exclusions\" banner, "
        "notification cards, the Recipe builder, mood chips) is converted to "
        "light with dark, legible text — nothing renders as a stray dark box "
        "on a light background anymore.",
        "Graphite is now a distinctly lighter, neutral charcoal — its own "
        "elevation ramp between backgrounds/bars/cards, clearly different from "
        "Midnight at a glance, not a 6-token reskin.",
        "Switching the theme in Settings now live-restyles more of the app "
        "without a restart: the sidebar Settings button, bottom nav bar, "
        "\"showing hidden\" banner text, the context-filter chip's dismiss "
        "button, and the whole middle filter column (every facet section, "
        "row, and checkbox).",
        "Quality chips (4K/FHD/HD/RAW/LIVE), OK/warn/error status colors, and "
        "the mood chips keep their existing hues and stay mutually "
        "distinguishable in every theme.",
    ),
    version="0.23.0",
    date="2026-08-03",
    test_steps=(
        "Settings → Interface → Appearance → switch to Daylight — the app "
        "background, sidebar, and channel list all go light with dark text; "
        "nothing stays a dark rectangle.",
        "While still on Daylight, open a source with hidden/excluded channels "
        "showing (right-click \"Show hidden\") — the \"Showing hidden and "
        "excluded channels\" banner is a light amber bar with dark text, not "
        "dark olive.",
        "On Daylight, open the middle filter column (facet panel next to the "
        "channel list) — it repaints light immediately on switching themes, "
        "no restart needed; expand a section and confirm the row checkboxes "
        "and labels are legible.",
        "On Daylight, trigger a notification (e.g. add/edit a source) and open "
        "the Recipe tab — both are light with legible text, not dark.",
        "Switch to Graphite — the app is visibly a lighter, neutral charcoal "
        "compared to Midnight, not the same near-black.",
        "In any theme, open a channel list row with a 4K badge next to one "
        "with an HD badge — the two colors are still clearly different from "
        "each other.",
        "Switch back to Midnight — the app matches its original appearance "
        "exactly (no leftover Daylight/Graphite styling).",
    ),
)
