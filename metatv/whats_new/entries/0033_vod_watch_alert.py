from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=33,
    version="0.8.0",
    date="2026-06-22",
    title="VOD Watch Alerts",
    items=(
        "New 'Watch for…' feature in the Alerts sidebar: click the '+' button to "
        "watch for a movie or series by title or keyword. You'll be alerted with a "
        "toast notification when matching content appears on any of your sources.",
        "Rules are scoped by content type (Movie, Series, or Any) and remember which "
        "channels have already been alerted, so you're never notified twice for the "
        "same match.",
        "Matching content is checked when you refresh a source and on startup. Active "
        "rules are listed in the new 'Watching for' sub-group inside the Alerts section; "
        "click 'Manage…' to see all rules and remove any you no longer need.",
    ),
)
