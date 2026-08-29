from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=432,
    version="0.54.0",
    date="2026-08-29",
    title="EPG matching gets the channel IDs it was always meant to use",
    items=(
        "Sources send a proper EPG channel ID with each channel, and the app "
        "read it, then threw it away before saving - on every channel, since "
        "the beginning.",
        "So the most reliable way of matching a channel to its guide has "
        "never once been used; everything fell back to matching by name.",
        "The ID is now saved, and the ones already sitting unused in stored "
        "source data are recovered on next launch - 20,506 of them on a large "
        "library.",
        "Two background EPG jobs also still ran for expired sources. They now "
        "skip them, so alerts no longer fire for content you cannot watch.",
    ),
    test_steps=(
        "Launch and let the recovery run, then open the EPG view and confirm "
        "more channels show programme data than before.",
        "Check a channel that previously had an empty guide despite the "
        "source offering one.",
        "Expire or disable a source and confirm no watch alerts arrive for "
        "its programmes.",
    ),
)
