from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=148,
    version="0.10.0",
    date="2026-07-22",
    title="Pointing-hand cursor now consistent on every clickable control",
    items=(
        "The app-wide pointing-hand cursor (added earlier for buttons and filter "
        "chips) now also shows on every non-button clickable — the details poster, "
        "tag/genre/cast chips, collapse/expand carets and section headers, "
        "clickable rows (Alerts, EPG watchlist, Similar Titles, Discover cards), "
        "and copy-to-clipboard labels — routed through the same single "
        "app-level affordance instead of scattered one-off code.",
        "Checkboxes and radio buttons keep the normal arrow cursor (the box/circle "
        "is already the affordance) — unchanged.",
    ),
    test_steps=(
        "Hover a details-pane poster with an image loaded → pointing hand; hover "
        "a poster with no image → normal arrow.",
        "Hover a genre/cast/tag chip, a Discover card, or a sidebar section's "
        "collapse caret → pointing hand cursor in every case.",
        "Hover a checkbox or radio button (e.g. in a filter panel or Settings) → "
        "cursor stays the normal arrow, not a hand.",
    ),
)
