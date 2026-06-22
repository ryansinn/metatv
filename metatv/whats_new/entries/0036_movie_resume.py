from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=36,
    version="0.8.0",
    date="2026-06-22",
    title="Movie Resume-Seek",
    items=(
        "Playing a partially-watched movie now resumes from where you left off — "
        "no more restarting from the beginning every time.",
        "The resume position is set directly via mpv's per-file start option, so "
        "playback begins at the right spot instantly with no seek-after-load delay.",
        "Live channels and completed movies always start from the beginning. "
        "Mark a movie as unwatched to reset the resume point.",
    ),
)
