from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=690,
    version="0.135.0",
    date="2026-10-09",
    title="Get stream details without playing",
    items=(
        "Details has a 'Get stream details' button: MetaTV opens the stream "
        "briefly in the background and records its resolution, frame rate, "
        "codecs, bitrate and audio/subtitle tracks — no player window.",
        "It waits its turn for the source's connection and steps aside if you "
        "start playing.",
    ),
    test_steps=(
        "Select a movie you have never played, open 'Details for …', press "
        "'Get stream details' — it reads 'Checking stream…' for ~10 seconds, then "
        "Resolution / Video / Audio / Subtitles rows appear with '· probed <date>'.",
        "The button now reads 'Re-check stream'; press it again — the rows refresh.",
        "While something from the same source is playing, press it — the status bar "
        "says the source's connection is in use, and playback is not interrupted.",
        "Press it on an offline channel — the status bar says the stream couldn't be read.",
    ),
)
