from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=689,
    version="0.134.0",
    date="2026-10-09",
    title="Details shows what a stream really is",
    items=(
        "When a channel plays, MetaTV records its real resolution, frame rate, "
        "HDR, video codec and bitrate, and every audio and subtitle track, and "
        "shows them first in Details — '· seen when played'.",
        "A stream named 4K that actually plays at 1080p says so.",
    ),
    test_steps=(
        "Play a movie or channel for a few seconds — its Details gains Resolution, "
        "Video, Audio and Subtitles rows with '· seen when played <date>'.",
        "Keep it playing past 30 seconds, reselect it — the Video row shows a bitrate.",
        "Play something whose name says 4K but is really 1080p — Resolution reads "
        "'… · says 4K, plays 1080p'.",
        "A stream with several audio tracks lists each language (English, Spanish…).",
    ),
)
