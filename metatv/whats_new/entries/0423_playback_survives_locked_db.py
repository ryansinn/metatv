from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=423,
    version="0.53.0",
    date="2026-08-29",
    title="Playing an episode during a source refresh no longer crashes the app",
    items=(
        "While a large source was refreshing, playing an episode could kill "
        "the app outright.",
        "The refresh holds the database busy, and recording 'you played this' "
        "failed - which took the whole program down instead of just skipping "
        "the note.",
        "Playing now always wins: if the play count or the up-next queue "
        "cannot be saved right then, the episode still plays and the problem "
        "is written to the log.",
    ),
    test_steps=(
        "Start a refresh of a large source, and while it runs, play an "
        "episode from History. It should play, and the app should stay open.",
        "Do the same with a movie or live channel.",
        "With no refresh running, play an episode and confirm the play count "
        "and the up-next queue still behave normally.",
    ),
)
