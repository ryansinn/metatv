from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=556,
    version="0.86.0",
    date="2026-09-03",
    title="Closing the player keeps your exact spot",
    items=(
        "Closing mpv now persists your exact position, even if it happens "
        "between the periodic 20-second checkpoints — previously a movie "
        "or single episode could lose its last few seconds of progress if "
        "the player exited (EOF or a manual quit) right after a checkpoint.",
        "A movie watched to its end is now marked finished even when mpv "
        "exits before the next checkpoint, instead of staying stuck at a "
        "partial percentage with a Resume button.",
    ),
    test_steps=(
        "Play a movie, let it reach the very end (or fast-forward near the "
        "end) and let mpv exit on its own → the row shows completed, no "
        "Resume button.",
        "Play a movie partway through and close mpv manually right after a "
        "checkpoint tick → reopening it resumes from very close to where "
        "you left off, not from an earlier checkpoint.",
    ),
)
