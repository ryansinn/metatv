from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=501,
    version="0.64.0",
    date="2026-09-01",
    title="A one-second freeze, every minute, for as long as the app was open",
    items=(
        "MetaTV checked your watch list against the guide once a minute to "
        "warn you when something was about to start — and did the whole check "
        "on the same thread that draws the window. With a large guide that is "
        "about a second of the app not responding, once a minute, forever.",
        "The check now runs in the background. Nothing about the alerts "
        "changes: the same programmes, the same warning time, the same "
        "notification.",
        "It also waits its turn behind a guide download instead of piling up "
        "behind one, so a slow source no longer means a burst of alerts all "
        "arriving at once when it finishes.",
    ),
    test_steps=(
        "Leave the app open and idle for five minutes with a watch list set, "
        "and confirm the window stays responsive throughout.",
        ("Set a watch-list rule for something starting soon and confirm the "
         "notification still appears at the right time.", "view:list"),
        "Refresh a source's guide and confirm alerts still arrive afterwards "
        "rather than all at once.",
    ),
)
