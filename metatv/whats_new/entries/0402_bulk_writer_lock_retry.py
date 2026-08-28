from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=402,
    version="0.52.0",
    date="2026-08-27",
    title="A one-time setup pass could stop on a busy database",
    items=(
        "The one-time passes that fill in title ids and matching keys write in "
        "batches. If the app was reading from the database at the same moment "
        "one of those batches saved, SQLite could report it as busy.",
        "Three of the five passes already handled that by waiting and trying "
        "the batch again. Two did not, and would stop instead - leaving the "
        "pass to start over on the next launch.",
        "All five now retry the same way. A retry redoes the whole batch, not "
        "just the save, because the earlier attempt's pending changes are "
        "discarded when it fails.",
        "A check now fails the build if a new bulk write is added without "
        "this, so the next one cannot quietly miss it the way these two did.",
    ),
    test_steps=(
        "On a fresh install, let the one-time setup passes run while browsing "
        "the app - the passes should complete rather than stopping partway.",
        "Check the log for 'locked (attempt 1/...); retrying' - if it appears, "
        "the pass should still finish rather than abort.",
        "Confirm titles still show their year and group with their other "
        "copies after setup completes.",
        "Restart the app and confirm the setup passes do not run again.",
    ),
)
