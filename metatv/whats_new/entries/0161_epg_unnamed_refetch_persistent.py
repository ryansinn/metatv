from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=161,
    version="0.10.0",
    date="2026-07-30",
    title="EPG no longer re-downloads the whole guide on every launch",
    items=(
        "Some sources serve guide entries with no channel name attached. MetaTV "
        "used to re-download that source's entire EPG on every single startup "
        "trying to fill the missing names — ignoring your refresh interval and "
        "slowing launch.",
        "Now MetaTV remembers it already tried once (the attempt is recorded "
        "persistently, not just for the session), so it stops re-fetching and lets "
        "your normal EPG refresh schedule take over.",
        "Refreshing the source's content gives the feed one fresh attempt — so if "
        "the provider fixes their guide, the names still get picked up.",
        "Sources whose names DO come through on the first re-fetch keep working "
        "exactly as before; nothing changes for a healthy EPG feed.",
    ),
    test_steps=(
        "With a source whose EPG has unnamed/unmatched guide rows (e.g. one serving "
        "placeholder/foreign EPG), launch the app twice. Expected: the full-guide "
        "EPG re-fetch happens at most once, not on the second launch — check the "
        "logs for a single 'triggering one-time re-fetch to populate channel names' "
        "line, not one per launch.",
        "Confirm the EPG still refreshes on its normal schedule: leave the app open "
        "past the source's refresh interval (or set a short one) and verify the "
        "guide updates on time — the interval is respected, the launch loop is gone.",
        "Refresh that source's content (re-load its channels), then relaunch: the "
        "app is allowed exactly one more names re-fetch attempt (marker reset by the "
        "content refresh), then stops again.",
    ),
)
