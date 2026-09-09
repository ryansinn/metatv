from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=654,
    version="0.112.0",
    date="2026-09-08",
    title="Background writers now queue instead of racing each other",
    items=(
        "EPG fetches, TMDb/metadata enrichment, migrations, the signal checker, "
        "stream-retry checks, downloads/recordings, and the profile store/watchlist "
        "each save to the database on their own schedule, and SQLite only allows one "
        "writer at a time. When a provider was slow, several of these could pile up "
        "and try to save at once, burning time retrying against a locked database "
        "instead of just taking turns. Background saves now share one orderly queue "
        "(capped at one at a time, since a second writer could not get in anyway) "
        "instead of colliding — favorite/rating/queue toggles and other on-screen "
        "actions are untouched and stay instant.",
    ),
    test_steps=(
        "Start a download and, while it is running, trigger an EPG refresh (or let "
        "a scheduled one fire) — both keep progressing normally with no 'database is "
        "locked' errors in the logs and the app stays responsive throughout.",
        "Add or remove a watch-list rule while a source refresh or metadata "
        "enrichment pass is running in the background — the rule change saves and "
        "appears in the list as usual, with no delay visible on screen.",
    ),
)
