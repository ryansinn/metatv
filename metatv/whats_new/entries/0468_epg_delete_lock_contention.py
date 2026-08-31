from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=468,
    version="0.60.0",
    date="2026-08-31",
    title="Refreshing a source no longer fails while the guide is being rebuilt",
    items=(
        "A source refresh could die part-way through with \"database is "
        "locked\", throwing away several minutes of work and leaving the "
        "source only partly updated.",
        "The cause was the TV guide. Before importing a new guide, MetaTV "
        "clears the old one — and it did that as a single instruction. On a "
        "large library that one instruction held the database to itself for "
        "69 seconds, measured. Anything else that needed to write during that "
        "window waited 30 seconds and then gave up: the source refresh, and "
        "the connection-speed figures used to pick the fastest server.",
        "The guide is now cleared in small batches, so the database is handed "
        "back constantly instead of being held. The longest any other job now "
        "waits is under a second — and clearing the guide got faster too, "
        "69 seconds down to 43.",
        "The same fix covers the other four places that clear guide data: "
        "turning EPG off for a source, the nightly sweep of finished "
        "programmes, and deleting a source.",
    ),
    test_steps=(
        ("Refresh a source that has a TV guide loaded and let it run to the "
         "end. It should report success, not \"database is locked\".",
         "view:sources"),
        "While that refresh is running, start a second source refreshing. "
        "Both should finish successfully.",
        ("Turn EPG off for a source with a full guide, then confirm On Now "
         "and Watch Alerts show no leftover programmes from it.",
         "view:sources"),
        "Turn EPG back on and refresh the guide; confirm programmes reappear "
        "and the app stays responsive throughout.",
        "Delete a source that has a guide loaded and confirm the delete "
        "completes without a lock error.",
    ),
)
