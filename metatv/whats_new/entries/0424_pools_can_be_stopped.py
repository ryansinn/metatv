from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=424,
    version="0.53.0",
    date="2026-08-29",
    title="Background workers all stop when they should",
    items=(
        "Eight parts of the app started background workers that nothing could "
        "stop - the similar-titles preview, the Preferences view, and every "
        "sidebar section.",
        "A worker still running while the things it touches are being torn "
        "down is what causes the crashes on quit.",
        "They can all be stopped now, and the app stops them.",
        "Switching away from Preferences also stops its worker, rather than "
        "leaving it running until you quit.",
    ),
    test_steps=(
        "Open a similar-titles preview, close it, and keep using the app.",
        "Visit Preferences, switch to another view, then quit - the app "
        "should exit cleanly.",
        "Expand several sidebar sections so they load, then quit immediately.",
    ),
)
