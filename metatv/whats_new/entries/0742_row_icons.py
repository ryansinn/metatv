from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=742,
    version="0.179.0",
    date="2026-10-19",
    title="List rows: a pink heart for favourites, clean watch-state icons",
    items=("Rows in the channel list mark favourites with a pink heart (an outline heart "
           "otherwise), show in-progress and watched as clean icons, and mark new "
           "Watch-Alert matches with a bell — the same icons as the details pane.",),
    test_steps=("Search for a title you've favourited — its row starts with a pink heart; "
                "other rows show a faint outline heart.",
                "Find a partly-watched movie — its row shows an orange play icon after the "
                "heart; a watched one shows a green check; an untouched one a small dot."),
)
