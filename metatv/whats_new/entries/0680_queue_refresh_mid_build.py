from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=680,
    version="0.127.0",
    date="2026-10-01",
    title="The Queue no longer crashes the app when it refreshes mid-load",
    items=(
        "If the Queue section refreshed while its rows were still being built — "
        "a long queue, right after launch or a change — the app could abort with "
        "\"QListWidgetItem has been deleted\". The unfinished build is now stopped "
        "before the list is cleared, and filtering the queue while it shows "
        "\"Loading…\" is safe too.",
    ),
    test_steps=(
        "With a long queue, launch the app and immediately queue or unqueue a "
        "title — the Queue reloads and the app keeps running.",
        "Open the Queue's find box and type while the section shows \"Loading…\" — "
        "no crash; the filter applies once the rows arrive.",
    ),
)
