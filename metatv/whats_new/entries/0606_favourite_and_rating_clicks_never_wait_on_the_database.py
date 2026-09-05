from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=606,
    version="0.99.0",
    date="2026-09-05",
    title="Favourite and rating clicks never wait on the database",
    items=(
        "Liking, disliking, favouriting, or hiding a title from Watch Alerts "
        "no longer stalls the window while a background refresh holds the "
        "database.",
    ),
    test_steps=(
        "Start a Refresh All, then favourite several rows quickly — the "
        "window stays responsive and each star lands.",
        "Like a title — the details pane and the row update.",
    ),
)
