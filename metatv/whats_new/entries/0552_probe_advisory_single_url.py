from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=552,
    version="0.85.0",
    date="2026-09-02",
    title="A single-address source's inconclusive probe lets mpv decide",
    items=(
        "On a source with a single address, a pre-flight timeout no longer "
        "blocks the play behind a 5-second probe, shows a wrong 'stream "
        "unavailable' toast, or damages that address's reliability stats — "
        "the player is launched and judges for itself, and a stream that "
        "truly never starts is still reported within ~16 seconds by the "
        "playback watch.",
        "Sources with alternate addresses keep the full probe-and-failover "
        "behavior unchanged.",
    ),
    test_steps=(
        "Play a slow-to-answer stream on a single-address source: mpv opens "
        "promptly with no 'stream unavailable' toast, and the source's "
        "reliability percentage does not drop from the attempt.",
        "Play a genuinely dead stream on that source: the 'Stream did not "
        "start' report still arrives within ~16 seconds.",
    ),
)
