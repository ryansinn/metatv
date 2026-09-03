from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=568,
    version="0.89.0",
    date="2026-09-03",
    title="Settings → Content gains a Live catalog refresh rate",
    items=(
        "A new \"Live catalog refresh\" setting in Settings → Content controls "
        "how often live channels and fixtures re-sync in the background, "
        "independent of the per-source full-catalog Auto-refresh schedule.",
        "Manual (default) — only the Sports banner's \"Refresh sources\" "
        "button and the individual source refresh button do anything.",
        "\"Whenever Sports or Events opens\" refreshes the live catalog when "
        "you open either view, with a 5-minute cooldown shared between them "
        "so quickly switching between Sports and Events doesn't hammer your "
        "sources with duplicate requests.",
        "Every 15 minutes / 30 minutes / 1 hour / 3 hours refreshes on a "
        "fixed interval while the app is open.",
        "Every mode always skips a source that is currently streaming and "
        "retries it later — none of this can interrupt playback.",
    ),
    test_steps=(
        "Settings → Content → \"Live catalog refresh\" → hover the dropdown "
        "for the tooltip; the options are Manual, \"Whenever Sports or Events "
        "opens\", and 15m/30m/1h/3h.",
        "Set it to \"Whenever Sports or Events opens\", save, then open Sports "
        "→ a live-only refresh runs shortly after; immediately switch to "
        "Events → no second refresh (cooldown); wait 5+ minutes and revisit "
        "either view → a refresh runs again.",
        "Set it to \"Every 15 minutes\", start playing a channel from a "
        "source, wait past the interval → check the logs for \"currently "
        "streaming\" — the source is skipped, not interrupted.",
    ),
)
