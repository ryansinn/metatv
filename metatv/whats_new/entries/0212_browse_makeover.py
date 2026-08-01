from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=212,
    version="0.18.0",
    date="2026-08-01",
    title="EPG Browse results-list makeover",
    items=(
        "Browse now shows two new columns: Category (the channel's prefix, "
        "e.g. \"US\") and Quality (HD/FHD/4K/etc.), matching what On Now "
        "already shows — hover either for a plain-language explanation.",
        "When you have more than one enabled source, each row's Channel cell "
        "gets a small glyph showing which source it came from (single-source "
        "setups see no glyph — nothing new to look at).",
        "Sorted by Time (the default), the list now groups rows under "
        "\"Tonight · Fri Aug 1\" / \"Tomorrow · Sat Aug 2\" day headers — pick "
        "any other column to sort by and the day headers disappear.",
        "The footer now reads \"### programmes · times shown in your local "
        "time\" so the Time column's timezone is never ambiguous.",
        "Browse's column headers can now be dragged to reorder, and your "
        "chosen order is remembered between launches — same as On Now.",
    ),
    test_steps=(
        "Open EPG → Browse: confirm the columns read Time / Category / "
        "Channel / Quality / Show / Duration, and hovering Category or "
        "Quality on a row shows an explanatory tooltip.",
        "With the list sorted by Time (the default), scroll down — confirm "
        "\"Tonight · ...\" / \"Tomorrow · ...\" day-separator rows appear and "
        "are not clickable/selectable.",
        "Click the Channel column header to sort by it — confirm the day "
        "separators disappear; click Time's header again — confirm they "
        "come back.",
        "Drag a column header to reorder it, then close and reopen EPG — "
        "confirm the new order is remembered.",
        "Check the footer line at the bottom of Browse reads \"... "
        "programmes · times shown in your local time\".",
    ),
)
