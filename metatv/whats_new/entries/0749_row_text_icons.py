from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=749,
    version="0.186.0",
    date="2026-10-19",
    title="Status messages, banners and the playback readout use the same clean icons",
    items=("The channel-list banners (loading, filters suspended, exclusions suspended), "
           "the series breadcrumb, the no-sources Add Source button and the playback "
           "health readout show the app's one icon set instead of emoji. Season and "
           "episode ratings in the series tree show a gold star icon. Status-bar warnings "
           "and errors now start with the word Warning or Error.",),
    test_steps=("Play a stream — the playback readout in the header starts with a play "
                "icon followed by buffer, speed and drops.",
                "Search with filters that hide every match so filters are suspended — the "
                "banner above the list leads with a line icon, not an emoji.",
                "Open a series — season and episode ratings show a gold star icon beside "
                "the number."),
)
