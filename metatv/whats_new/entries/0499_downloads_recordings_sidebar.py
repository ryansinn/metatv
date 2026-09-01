from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=499,
    version="0.64.0",
    date="2026-09-01",
    title="Downloads and Recordings now have somewhere to appear",
    items=(
        "Downloading a title and recording a channel both worked already, but "
        "neither had anywhere to show what it was doing — so once you started "
        "one, the only way to find out how it was going was to look in the "
        "folder.",
        "There are now Downloads and Recordings sections in the sidebar. Each "
        "row says what it is doing in words — Queued, Downloading, Paused, "
        "Waiting for the source — with a bar for how far through it is, and a "
        "button to open the folder.",
        "A download that pauses itself because you started watching says so, "
        "rather than just saying Paused: on a source that allows one "
        "connection that is the app getting out of your way, not a fault.",
        "Both sections can be reordered, hidden or shown under Settings → "
        "Sidebar, like every other section.",
    ),
    test_steps=(
        ("Start a download and confirm the Downloads section shows it with a "
         "progress bar and a state.", "view:list"),
        "While it downloads, press play on something from the same source: "
        "the row should say it paused for playback, then resume when you stop.",
        ("Open Settings → Sidebar and confirm Downloads and Recordings can be "
         "reordered and hidden like the other sections.", "view:list"),
        "Use the folder button in each section's ⋯ menu and confirm it opens "
        "the right folder.",
        "Confirm an idle app with nothing downloading shows both sections "
        "empty rather than stale.",
    ),
)
