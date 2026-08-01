from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=180,
    version="0.15.0",
    date="2026-07-31",
    title="Similar Titles now respects your Global Filter",
    items=(
        "Similar-title suggestions honor your Global Filter exclusions everywhere "
        "they appear — the details-pane 'Similar Titles' row, the Similar Titles "
        "lightbox strip, and the Explore trail-map's similar columns. Languages or "
        "categories you've globally excluded (or blocked with 'Block [PREFIX]') no "
        "longer leak into suggestions.",
        "It uses the exact same blacklist Discover applies, and it follows your "
        "'show uncategorized' choice. Pausing the Global Filter brings the excluded "
        "suggestions back, just like everywhere else.",
    ),
    test_steps=(
        "Set a Global Filter exclusion for a language you see in suggestions (e.g. "
        "exclude a category/prefix like DE or NL). Open a title's details pane and "
        "confirm the 'Similar Titles' row no longer lists that language's titles.",
        "Open the Similar Titles lightbox for that title and confirm the strip is "
        "also free of the excluded language; click 'Explore' and confirm an expanded "
        "column's similar titles exclude it too.",
        "Pause the Global Filter and reopen: the previously-excluded similar titles "
        "reappear (confirming the filter, not a data change, was hiding them).",
    ),
)
