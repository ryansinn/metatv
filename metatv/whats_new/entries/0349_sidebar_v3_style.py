from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=349,
    version="0.41.0",
    date="2026-08-24",
    title="The sidebar looks like the sidebar it was designed as",
    items=(
        "Sidebar rows are two lines now: the title on top, and the detail that "
        "used to crowd it — year, language, episode — underneath in a quieter "
        "colour. A glance reads titles; a second look reads state.",
        "Each section is its own rounded card with a gap to its neighbour, so "
        "\"these five rows are History\" is visible without reading a heading.",
        "Group headings inside a section (Alerts Matched, Continue Watching) "
        "are small-caps and muted — a divider rather than another title "
        "competing with the rows beneath it.",
    ),
    test_steps=(
        "Open the sidebar → each section (Recommended, Watch Queue, Favorites, "
        "History) is a distinct rounded card with a visible gap between them.",
        "Look at a Watch Queue or History row → the title is on the first line "
        "and its year / language sit underneath in a quieter colour, not as "
        "chips crowding the title.",
        "A row with no extra detail (just a title) stays a single line — it "
        "does not grow an empty second one.",
        "Watch Queue → the \"ALERTS MATCHED\" and \"CONTINUE WATCHING\" headings "
        "read as small-caps dividers, quieter than the titles under them.",
        "Drag a section's splitter handle → it still resizes, and the gap "
        "between cards is the drag target.",
        "Switch themes (including Gruvbox and Daylight) → the cards, the meta "
        "line and the group headings all stay legible.",
    ),
)
