from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=555,
    version="0.86.0",
    date="2026-09-03",
    title="History updates the moment you press play",
    items=(
        "Playing something now puts it at the top of History right away, "
        "instead of sometimes needing a second play (or a manual refresh) "
        "to show up — the old refresh could run before the play had even "
        "finished writing to the database.",
        "The details pane's Resume/Play state now updates when playback "
        "ends, instead of staying frozen on what it showed before you "
        "started watching.",
    ),
    test_steps=(
        "Play a movie or channel from Recommended (or any non-validated "
        "path like 'Play Anyway') → it appears at the top of History within "
        "a second, no extra refresh needed.",
        "Play a movie partway through, close mpv, reopen the details pane "
        "for that title → the Resume button reflects the position you left "
        "off at.",
    ),
)
