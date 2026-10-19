from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=745,
    version="0.182.0",
    date="2026-10-19",
    title="TV guide and notifications use the same clean icons",
    items=("The TV guide's tabs, watchlist and pinned-channel cards, the progress "
           "notifications and the migration panel now show the app's one icon set "
           "instead of emoji.",),
    test_steps=("Open EPG — the tabs (Watchlist, My Channels, Discover, On Now, Browse, Manage, "
                "Events) each lead with a line icon.",
                "Refresh a source — the corner notification's title and each step "
                "(pending, working, done) show line icons in their state colours."),
)
