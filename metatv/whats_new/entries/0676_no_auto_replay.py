from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=676,
    version="0.124.0",
    date="2026-09-13",
    title="Playback never restarts on its own",
    items=(
        "A stream that failed to open used to be retried automatically after "
        "20 seconds, and one that dropped mid-film used to be relaunched from "
        "the cut, up to three times — both are gone. A failure is reported "
        "once (status line + toast + the failed-streams list) and the player "
        "is left as it is. A drop still saves your position, so Resume picks "
        "up where it died; you decide when to try again.",
    ),
    test_steps=(
        "Play a title that will not open — \"Nothing is playing\" appears and "
        "nothing restarts after 20 seconds.",
        "Mid-film, cut the network until the buffer runs out — the window "
        "closes with \"the stream dropped at M:SS\", nothing relaunches, and "
        "the title's details offer Resume at that position.",
        "Switch titles while one is failing — it is never interrupted by an "
        "old title coming back.",
    ),
)
