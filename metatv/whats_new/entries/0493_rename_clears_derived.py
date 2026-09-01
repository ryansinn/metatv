from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=493,
    version="0.64.0",
    date="2026-09-01",
    title="A channel showing the wrong programme's name",
    items=(
        "A sports channel could be listed under a game that finished days ago "
        "while actually carrying tonight's — the same slot, renamed by your "
        "source, but the app kept displaying the old name. Restarting did not "
        "help.",
        "Sports slots are reused: your source keeps the channel and rewrites "
        "its name for each day's fixture. The app already knew to discard the "
        "old artwork when that happened, but not the old title, so the stale "
        "one stayed on screen and in searches.",
        "A renamed channel now re-derives its title, and everything computed "
        "from it, on the next refresh.",
    ),
    test_steps=(
        ("Refresh a source after a sports slot has changed fixture, and "
         "confirm the list shows the new game rather than the old one.",
         "view:sports"),
        "Confirm ordinary channels keep their names and details after a "
        "refresh — nothing should be re-derived unnecessarily.",
        ("Search for a renamed fixture by its new name and confirm it is "
         "found.", "view:list"),
    ),
)
