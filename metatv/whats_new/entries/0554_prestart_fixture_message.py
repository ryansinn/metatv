from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=554,
    version="0.85.0",
    date="2026-09-02",
    title="Playing a fixture early now says so",
    items=(
        "Playing a sports fixture before its scheduled start now says so — "
        "\"This event hasn't started — scheduled for HH:MM\" (your local "
        "time) — in both the pre-flight toast and the stream-never-started "
        "report, instead of the generic \"the source may be busy or the "
        "stream dead\".",
    ),
    test_steps=(
        "Play a fixture whose listed start is hours away: the failure "
        "message names the local start time instead of guessing at the "
        "source.",
        "Play a fixture that already started and is genuinely dead: the "
        "generic report is unchanged.",
    ),
)
