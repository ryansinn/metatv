from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=438,
    version="0.54.0",
    date="2026-08-29",
    title="The EPG view no longer leaves a worker running behind it",
    items=(
        "Opening the guide started a background worker that was never stopped "
        "- not when you switched to another view, and not when you closed the "
        "window. It outlived the app.",
        "A thread still running while the things it touches are being torn "
        "down is what makes an app abort on quit rather than exit cleanly.",
        "The worker now stops when you leave the guide, and starts again when "
        "you come back.",
    ),
    test_steps=(
        "Open the EPG view, switch to another view, and confirm the guide "
        "still works normally when you switch back to it.",
        "Open the EPG view, load a tab that fetches data, switch away and back "
        "again, and confirm the data still loads.",
        "Quit the app from the EPG view and confirm it closes cleanly.",
    ),
)
