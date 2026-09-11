from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=668,
    version="0.120.0",
    date="2026-09-11",
    title="Episodes the player skipped are not marked watched, and closing mid-episode keeps your place",
    items=(
        "When a queued episode fails to open — a source that's busy and refuses "
        "the next connection — the player just moves on to the next one. That "
        "skipped episode used to be ticked as watched anyway; it no longer is.",
        "Closing the player partway through a queued episode used to mark it "
        "100% complete and throw away your position. It now keeps the position "
        "so Resume picks up where you left off.",
        "Answering \"No\" to \"Did you watch them?\" now only takes back the "
        "episodes the queue itself marked watched — an episode you were "
        "partway through, or never played, is left alone.",
    ),
    test_steps=(
        "Play-All a series where the second episode is unavailable (or make "
        "the source busy right as the first one ends) — the skipped episode "
        "must not show as watched (checkmark).",
        "With episodes queued, close the player about two minutes into one — "
        "reopen the series: that episode offers Resume around 2:00 and is not "
        "checked as watched.",
        "Let the last queued episode play through to the end — it shows as "
        "watched.",
    ),
)
