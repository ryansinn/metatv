from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=629,
    version="0.103.0",
    date="2026-09-07",
    title="The guide says why it is stale, and refreshes when it actually runs out",
    items=(
        "A source's guide freshness line used to read \"Stale - guide ends 4 Aug "
        "2026 (source out of date)\" whatever had gone wrong, which blamed the "
        "provider even when the fetch had failed on our side. It now says which "
        "of three things happened: the source has not published further, we "
        "could not fetch from any host, or your own EPG URL override is the "
        "thing failing. The failure states name the cause and when it started, "
        "with the full explanation on the tooltip.",
        "A broken URL override is now visible. It is deliberately never retried "
        "against other hosts - it is an explicit instruction - so before this it "
        "failed silently forever behind a line that pointed at the provider.",
        "The guide refresh no longer waits on a programme that merely runs LONG. "
        "It used to measure coverage by when the last programme ENDS, so a "
        "single late-night block could report hours of guide left after the last "
        "programme had already started - hours in which no watch alert could "
        "fire. It now refreshes when nothing new can start.",
        "Feeds that genuinely lag real time are still throttled rather than "
        "re-fetched on every check, so nothing loops.",
    ),
    test_steps=(
        "Sources -> pick a source -> Settings tab -> XMLTV URL override: type "
        "http://not-a-real-host.invalid/xmltv.php, Save, then press Refresh "
        "Guide. The Guide freshness line reads \"Your EPG URL override failed "
        "since <date, time>: <cause>\" in red with a cross; hover it for the "
        "full explanation, which says the override is never cycled to another "
        "host.",
        "Clear the override, Save, press Refresh Guide again. Once it completes "
        "the line goes back to \"Current - guide through <date>\" (green, no "
        "glyph) - or \"Guide ends <date> - the source has not published "
        "further\" (amber, warning glyph) if the feed itself is behind. Neither "
        "wording says \"source out of date\" any more.",
        "The same line appears on the Summary tab as \"EPG guide:\" - check it "
        "says exactly the same thing in both places.",
        "Watch Alerts: leave the app running past the moment the last programme "
        "in a source's guide STARTS (while it is still on air). The guide "
        "refreshes then instead of waiting for that programme to end, and alerts "
        "keep firing.",
    ),
)
