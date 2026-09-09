from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=655,
    version="0.114.0",
    date="2026-09-08",
    title="A provider refresh no longer rewrites every channel just to confirm it's still there",
    items=(
        "Every catalog refresh rewrote every single channel row — the full name, "
        "stream URL, artwork, category, and raw provider payload — even for the "
        "overwhelming majority that hadn't changed since the last refresh, purely to "
        "record 'the source still lists this'. Each refresh now checks whether a "
        "channel's full catalog payload actually differs from what's stored; an "
        "unchanged channel only gets its presence timestamp touched instead of a "
        "full rewrite. Measured on a 100,000-channel all-unchanged refresh: the "
        "store phase dropped from 34.5s to 1.5s. A source with real edits (renamed "
        "channels, new episodes, updated artwork) still gets those written "
        "immediately — only genuinely identical rows are skipped, and channels the "
        "source stops listing are still cleaned up exactly as before.",
    ),
    test_steps=(
        "Refresh a source twice in a row with nothing changed upstream — the second "
        "refresh completes noticeably faster than the first, and the channel list, "
        "favorites, and hidden/suppressed state are all unaffected.",
        "Rename a channel (or change its category) at the provider and refresh — the "
        "renamed channel's title/category updates in the list as before.",
        "Remove a channel from the provider's listing and refresh — the channel is "
        "still pruned from the catalog (unless favorited/played/queued) exactly as "
        "before.",
    ),
)
