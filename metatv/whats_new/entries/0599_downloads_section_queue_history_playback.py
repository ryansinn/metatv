from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=599,
    version="0.97.0",
    date="2026-09-05",
    title="The Downloads sidebar section works: queue, history, and playback",
    items=(
        "The Downloads sidebar shows what each download is doing and why — "
        "queued behind the source's one connection, paused because you "
        "started watching something, or held back by your free-space floor "
        "— with its speed and time left while it is actually running.",
        "Finished downloads move into their own history, grouped into the "
        "same Today/Yesterday/… segments as History. Clear one segment at a "
        "time (with Undo) or every finished download at once from the ⋯ "
        "menu — either way, it's only forgotten from the list: the files on "
        "disk and the Downloaded scope on the channel list are untouched.",
        "Double-click a finished download to play it. With Split Streams "
        "on, it opens in its own window so a live stream elsewhere keeps "
        "playing; with it off, it replaces the shared window.",
        "The ⋯ menu gains Pause all downloads / Resume all downloads, and a "
        "download's own menu gains Play and Delete file… (removes the file "
        "only — it stays in your history).",
    ),
    test_steps=(
        "Queue two downloads from the same one-connection source — the "
        "second one's row explains it is waiting for the connection.",
        "Start playing something on that source — the running download's "
        "row says it paused for playback, and resumes on its own once you "
        "stop watching.",
        "Let a download finish — it moves under a \"Today\" heading; "
        "double-click it and it plays. With Split Streams on, start a live "
        "stream first and confirm it keeps playing in its own window.",
        "Clear the \"Today\" group from its heading's forget button, then "
        "click Undo in the toast — the download reappears; the file on "
        "disk was never touched either way.",
    ),
)
