from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=513,
    version="0.67.0",
    date="2026-09-02",
    title="MetaTV stops phoning your source when you didn't ask it to",
    items=(
        "Two background jobs were querying your source constantly. Checking "
        "your watched series for new episodes made 234 separate requests per "
        "pass — a full source refresh makes ONE, takes about 34 seconds, and "
        "brings back the entire catalogue. Both are off now.",
        "Setting the series check to 'Never' also did not fully work: it "
        "stopped the repeating timer but a full pass still ran at every "
        "launch. The setting now covers both.",
        "The other job was filling in genres for every movie you own — half a "
        "million of them, 500 per launch, which would have taken about a "
        "thousand launches. Genres are still fetched for anything you actually "
        "open, which is what they were for.",
        "If you want either back on, they are in Settings. Nothing was "
        "removed.",
        "If you had these switched on before, they are switched off for you "
        "too — not just for a fresh install. Changing what a setting defaults "
        "to does nothing to a config file that already has the old value "
        "written into it, which is why the backfill kept running. Anything you "
        "deliberately set to your own number is left exactly as you set it.",
    ),
    test_steps=(
        ("Launch MetaTV and confirm the log has no 'tmdb_enrich: genre backfill' "
         "lines — the stored 500 should be migrated to 0 on first launch."),
        ("Launch MetaTV and confirm the log has no 'get_series_info' calls "
         "and no 'genre backfill' lines."),
        ("Confirm playback starts promptly without competing for the source's "
         "connection.", "view:browse"),
        ("Open a movie you have not viewed before and confirm its genre and "
         "plot still fill in.", "view:browse"),
        ("Set the series recheck interval to something other than Never, "
         "restart, and confirm the check runs again."),
        ("Set it back to Never, restart, and confirm no series polling "
         "happens at all — including at launch."),
    ),
)
