from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=675,
    version="0.123.0",
    date="2026-09-13",
    title="A stalled stream waits for its source instead of reconnecting",
    items=(
        "Since two days ago, a stream whose source paused for 20 seconds was "
        "dropped and reconnected — and on a source that answers reconnects "
        "slowly or not at all, that turned every title into \"it only plays "
        "the first two minutes\". The player now keeps the original connection "
        "through a stall, which is what played a 2.6-hour episode queue to the "
        "end on the same source before that change; a genuinely dead "
        "connection still ends on its own and reconnects as before.",
    ),
    test_steps=(
        "On the source that was cutting out at ~2 minutes, play a film and let "
        "it run past 5 minutes without touching it — it should keep playing "
        "(a brief pause is possible if the source stalls, but no drop).",
        "Seek ahead past the buffered part — it should resume within a minute.",
        "Pull the network for two minutes mid-play, then restore it — the "
        "player should reconnect or, if it closed, resume from the cut.",
    ),
)
