from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=623,
    version="0.102.0",
    date="2026-09-07",
    title="Status messages say when something went wrong",
    items=(
        "The status bar now marks a problem with a warning or error glyph "
        "instead of showing it in the same plain text as an ordinary hint "
        "like 'Favorite added'.",
        "Every warning/error status message is now also written to the log, "
        "so a problem the status bar reported can be found afterward.",
    ),
    test_steps=(
        "Play a channel from a source that is offline → the status bar "
        "message carries the warning/error glyph.",
        "Favorite a channel → the status bar's 'added to favorites' "
        "confirmation shows no glyph, and its wording is unchanged.",
    ),
)
