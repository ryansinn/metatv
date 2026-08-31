from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=465,
    version="0.60.0",
    date="2026-08-31",
    title="Closing traps before they went off",
    items=(
        "The Source Analytics screen was never told to stop when you closed "
        "the app, so its background queries could come back to a window that "
        "was already being torn down.",
        "The Sports and Events views had no deep link, so a \"Go ▸\" button "
        "in a What's New test step would have rendered and done nothing.",
        "Added checks that catch three whole classes of this: a migration "
        "that was written but never registered (it would silently never run), "
        "a view chip with no deep-link target, and a What's New step pointing "
        "at a screen the app cannot navigate to.",
    ),
    test_steps=(
        ("Open Sources, click into a source's analytics, then close the app "
         "while it is loading. It should shut down cleanly.", "view:browse"),
        ("Use a \"Go ▸\" button on a What's New step that targets Sports and "
         "confirm it actually lands on Sports.", "view:sports"),
        ("Same for one targeting Events.", "view:events"),
    ),
)
