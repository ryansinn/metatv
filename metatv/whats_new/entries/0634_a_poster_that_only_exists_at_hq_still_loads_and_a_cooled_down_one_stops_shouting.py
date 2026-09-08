from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=634,
    version="0.103.0",
    date="2026-09-08",
    title="A YouTube-hosted poster that only exists at HQ still loads",
    items=(
        "Some sources point a title's poster at a YouTube thumbnail. The "
        "maxresdefault.jpg they name exists only for videos with an HD "
        "thumbnail; the hqdefault.jpg sibling exists for every video, so it is "
        "now tried when the first one is missing.",
        "A poster already known to be missing was re-requested by every surface "
        "that showed the title — four times in one second when playback "
        "stopped — and each request logged a warning for zero network "
        "activity. The negative cache is now a quiet debug line.",
        "The \"Waiting for <source> to answer… Ns\" countdown is a status line, "
        "not a warning: it no longer writes a warning to the log every two "
        "seconds.",
    ),
    test_steps=(
        "Open a title whose poster URL is a YouTube maxresdefault.jpg that does "
        "not exist → the poster still appears (from hqdefault).",
        "Play a title whose poster cannot be downloaded, then stop it → the log "
        "shows one download failure, then 'cooldown: no candidate tried' at "
        "debug level, no repeated warnings.",
        "Start a stream on a slow source → the status bar counts down; the log "
        "carries no warning per tick.",
    ),
)
