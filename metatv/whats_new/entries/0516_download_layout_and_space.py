from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=516,
    version="0.68.0",
    date="2026-09-02",
    title="Downloads land where a media server can find them",
    items=(
        "Downloads now go into a Movies/ and Series/Show/Season 02/ tree "
        "instead of one flat pile. Plex, Jellyfin and Kodi read that layout "
        "without being configured.",
        "Anything MetaTV does not know enough about stays flat rather than "
        "being filed into a made-up folder. A tree built on guesses is worse "
        "than a flat one, so a film with no year and an episode with no "
        "season number keep a plain filename.",
        "Downloads also stop before they fill your disk: they will not take "
        "free space below 10 GB. A download already in progress finishes if "
        "what is left of it fits, and stops immediately if it does not — with "
        "the reason on its row.",
        "The layout and the floor are not yet in Settings, so they use those "
        "defaults for now.",
    ),
    test_steps=(
        ("Download a movie that has a year, and confirm the file appears "
         "under Movies/ as 'Title (Year).ext'.", "view:browse"),
        ("Download an episode and confirm it appears under "
         "Series/<Show>/Season NN/.", "view:browse"),
        ("Download something with sparse metadata and confirm it lands as a "
         "plain filename in the downloads root, NOT in a folder named "
         "Unknown or Season 00.", "view:browse"),
        ("Confirm a queued download does not start when free space is "
         "already below 10 GB, and that its row says the floor was reached."),
    ),
)
