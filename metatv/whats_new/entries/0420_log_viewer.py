from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=420,
    version="0.53.0",
    date="2026-08-29",
    title="A live log window, and a way to clear the logs",
    items=(
        "Tools > Log viewer opens a floating window you can push aside, "
        "filling with log lines as the app runs.",
        "Filter by level or by text - nothing is thrown away, so widening "
        "the filter brings earlier lines back.",
        "Save what you are looking at to a file, or copy a diagnostics "
        "summary for a bug report. It carries version and paths only, never "
        "anything about your subscription.",
        "Tools > Clear log files deletes every log, rotated copies included, "
        "and tells you how much space it freed.",
    ),
    test_steps=(
        "Open Tools > Log viewer, then browse the app - new lines should "
        "appear as you go.",
        "Set the level to WARNING, then back to DEBUG, and confirm the "
        "earlier lines come back rather than staying gone.",
        "Type in the filter box and confirm it narrows the view.",
        "Click Save log and confirm the file is written.",
        "Click Copy diagnostics and paste it somewhere - it should name the "
        "build and log path and nothing about your provider.",
        "Close the window, keep using the app, and reopen it - it should "
        "still work and not show every line twice.",
        "Run Tools > Clear log files, confirm the prompt, and check the log "
        "folder is emptied.",
    ),
)
