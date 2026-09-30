from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=678,
    version="0.126.0",
    date="2026-09-29",
    title="A stalled stream no longer locks itself out",
    items=(
        "On a one-connection source, a stream that paused for a minute used to be cut by the "
        "player, which then tried to reconnect while still holding the old connection — the "
        "source refused it (HTTP 509) and every queued episode after it failed until the player "
        "was closed. The player now waits on the original connection, so the stream resumes.",
    ),
    test_steps=(
        "Play a series episode with the rest of the season queued on a one-connection source — "
        "episodes advance one after another; the log shows no 'HTTP error 509'.",
        "If the source pauses mid-episode, playback waits and resumes on its own instead of "
        "looping 'Will reconnect … HTTP error 509' in the log.",
    ),
)
