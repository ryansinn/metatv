from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=72,
    version="0.9.0",
    date="2026-06-27",
    title="Details pane: variant chip queue label + genre chip wrapping",
    items=(
        "Right-clicking an 'Also available as:' variant chip now shows 'Remove from Queue' "
        "when that variant is already queued, and 'Add to Queue' when it is not. "
        "The chip icon also updates immediately after toggling.",
        "Genre chips in the details pane now wrap to multiple lines when there are many genres, "
        "preventing horizontal overflow of the details panel.",
    ),
    test_steps=(
        "Open the details pane for a movie or series that has a variant in your Watch Queue "
        "(the variant chip should show the queue icon). Right-click the variant chip "
        "→ menu should say 'Remove from Queue', not 'Add to Queue'.",
        "Select 'Remove from Queue' from the chip menu → the chip icon updates to remove "
        "the queue indicator, and right-clicking again shows 'Add to Queue'.",
        "Open details for a title with many genres (e.g. a documentary with 5+ genres) "
        "→ the genre chips should wrap onto multiple lines inside the details panel "
        "rather than overflowing horizontally.",
        "Click a genre chip → the channel list filters to that genre (context filter chip "
        "appears in the search bar).",
    ),
)
