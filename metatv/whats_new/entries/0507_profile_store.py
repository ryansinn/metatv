from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=507,
    version="0.65.0",
    date="2026-09-01",
    title="Your selections moved out of the settings file",
    items=(
        "Most of config.yaml was never settings. On a real library, 1,849 of "
        "its 2,252 lines were your own state — which genres you have already "
        "been shown, what you have excluded, the series you monitor — and "
        "changing any single checkbox rewrote all of it, because a file can "
        "only be written whole.",
        "That state now lives in the database, one row per thing, so a change "
        "writes the one row that changed. The settings file keeps the actual "
        "settings and gets noticeably smaller.",
        "The move happens once, on the next launch, and it is verified: each "
        "piece is written, read back and compared before it is removed from "
        "the file. Anything that does not match stays where it was and says so "
        "in the log. Your selections should look exactly as you left them.",
    ),
    test_steps=(
        ("Launch MetaTV, then open the filter panel and confirm your included "
         "genres, regions and languages are exactly as you left them.",
         "view:browse"),
        ("Open Global Exclusions and confirm your excluded categories are "
         "unchanged."),
        ("Open Watch Alerts from the sidebar and confirm your monitored "
         "series and VOD alert rules are all still listed."),
        ("Toggle a genre off, restart MetaTV, and confirm it is still off."),
        ("Un-tick a genre so that NONE are selected, restart, and confirm the "
         "selection is still empty rather than reset to all-selected."),
        ("Open ~/.config/metatv/config.yaml and confirm the filter_known_*, "
         "filter_included_* and monitored_series keys are gone while your "
         "theme and other settings remain."),
        ("Check the log for 'profile: migrated N key(s)' on the first launch, "
         "and confirm no line says a key 'did not survive the round trip'."),
    ),
)
