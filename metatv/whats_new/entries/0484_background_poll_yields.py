from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=484,
    version="0.64.0",
    date="2026-08-31",
    title="A channel that opens and vanishes",
    items=(
        "A channel would open an mpv window that disappeared a second later "
        "with nothing played and no error shown. It had worked the night "
        "before, and nothing in the app had changed.",
        "The provider had got slow — the series check that runs in the "
        "background went from a fraction of a second to about eleven seconds "
        "per request. A watchlist pass that used to take twenty seconds "
        "started taking eleven minutes, so it was almost always running.",
        "Most accounts allow one connection at a time. That background check "
        "was holding it while you were watching, so the provider dropped the "
        "stream — and mpv exits silently when its stream ends, which is why "
        "the window simply vanished.",
        "Playing, downloading and recording now all take priority over the "
        "background check, which steps aside and catches up on its next pass.",
        "Separately, two copies of the same library-wide enrichment sweep "
        "could run at once and block each other. That is what made a source "
        "refresh fail outright, and what kept the app from closing for the "
        "better part of a minute. Only one runs now.",
    ),
    test_steps=(
        ("Play a channel and leave it running for a minute or two. It should "
         "keep playing rather than closing on its own.", "view:channels"),
        ("With something playing, confirm the Watch Alerts series check does "
         "not interrupt it.", "view:alerts"),
        "Start a download while a channel is playing — both should continue.",
        "Refresh a source and confirm it completes rather than reporting a "
        "failure, and that the app closes promptly afterwards.",
    ),
)
