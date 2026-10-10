from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=707,
    version="0.147.0",
    date="2026-10-09",
    title="Stream details and original language from your source, for free",
    items=(
        "Your source already describes each movie file (resolution, codecs, bitrate, "
        "audio language) and passes on TMDb's original language. Opening a movie now "
        "asks it once and shows those in Details — '· reported by the source' — "
        "without opening the stream. Opening a series stores the same for every "
        "episode.",
        "A real measurement (played, or Get stream details) always wins over what the "
        "source reports, and is never overwritten by it.",
        "Clicking the source chip in Details copies the channel id again.",
    ),
    test_steps=(
        "Open a movie you have never played — within a second or two Details shows "
        "Resolution / Video / Audio '· reported by the source' and 'Original language'.",
        "Play it for a few seconds and reselect — the rows now say '· seen when played'.",
        "Open a series, select an episode — its stream rows appear without playing.",
        "Click the source chip under the title — the status bar says the channel id was "
        "copied; paste — it is the id.",
    ),
)
