from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=206,
    version="0.17.0",
    date="2026-08-01",
    title="Recoverable remove in Manage Watch Alerts",
    items=(
        "Removing a keyword rule or stopping a monitored series in \"Manage "
        "Watch Alerts\" is no longer instant and irreversible — the row flips "
        "to strikethrough with an \"Undo\" button in place of Remove/Stop.",
        "Nothing is actually deleted until you close the dialog — click Undo "
        "any time before then to restore the rule or series exactly as it "
        "was, match history included.",
        "Closing the dialog (Close button, Esc, or the window's X) finalizes "
        "any rows still marked for removal.",
    ),
    test_steps=(
        "Open Manage Watch Alerts, click Remove on a keyword rule → the row "
        "goes strikethrough and the button becomes 'Undo'; the rule is still "
        "listed, not gone.",
        "Click Undo → the row returns to normal (Remove button back, no "
        "strikethrough).",
        "Click Remove again, then close the dialog → the rule is gone from "
        "the list the next time you open Manage Watch Alerts.",
        "Repeat with a monitored series' 'Stop' button → same "
        "strikethrough/Undo/finalize-on-close behavior.",
    ),
)
