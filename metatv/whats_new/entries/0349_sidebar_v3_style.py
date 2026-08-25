from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=349,
    version="0.41.0",
    date="2026-08-25",
    title="The sidebar looks like the sidebar it was designed as",
    items=(
        "Sidebar rows are two lines now: the title on top, and the detail that "
        "used to crowd it underneath in a quieter colour. A glance reads "
        "titles; a second look reads state.",
        "The chips are gone from sidebar rows. Year, language and quality read "
        "as \"Movie · 1985 · EN · 4K\" on the second line instead of three "
        "badges stacked against the right margin taking the width the title "
        "needed. (The channel list keeps its chips — that is where they earn "
        "their space.)",
        "History rows say WHEN: \"S18E01 · 2 hours ago\", \"1984 · yesterday\". "
        "The episode code moved off the end of the title, where it had been "
        "competing with the name it belongs to.",
        "Each section is its own rounded card with a gap to its neighbour, so "
        "\"these five rows are History\" is visible without reading a heading.",
        "Group headings inside a section (Alerts Matched, Continue Watching, "
        "EPG) are small-caps and muted — a divider rather than another title "
        "competing with the rows beneath it. Watch Alerts now matches the other "
        "sections; it had its own hand-rolled heading style.",
        "A section will no longer show you \"+ 6 more →\" with nothing above "
        "it. One real row always wins over the marker that counts them.",
    ),
    test_steps=(
        "Open the sidebar → each section (Recommended, Watch Queue, Favorites, "
        "History) is a distinct rounded card with a visible gap between them.",
        "Look at a Watch Queue or Favorites row → the title is on the first "
        "line and \"Movie · 1985 · EN · 4K\" sits underneath in a quieter "
        "colour, with no chips or badges anywhere in the row.",
        "Look at a History row → the second line ends with a time "
        "(\"2 hours ago\", \"yesterday\", \"last week\"), and a series row "
        "leads it with the episode code instead of appending it to the title.",
        "A row with nothing extra to say (a live channel you have never "
        "played) stays a single line — it does not grow an empty second one.",
        "Watch Queue → the \"ALERTS MATCHED\" and \"CONTINUE WATCHING\" "
        "headings read as small-caps dividers, quieter than the titles under "
        "them; Watch Alerts' \"EPG\" / \"MOVIES & SERIES\" headings match them.",
        "Watch Queue → type in the find box: filtering still finds rows by "
        "title, year and provider name, and the heading counts still read "
        "\"Never Watched (2 of 3)\".",
        "Drag a section's splitter handle down until the section is short → it "
        "always keeps at least one visible row above the \"+ N more →\" link, "
        "never the link alone.",
        "Drag a section taller → more rows appear, and the sections still "
        "cannot be dragged below a height that fits three rows.",
        "Switch themes (Midnight, Graphite, Daylight, Gruvbox, Gruvbox Light) "
        "→ the cards, the two-line rows and the group headings all stay "
        "legible, with the second line quieter than the title in every one.",
    ),
)
