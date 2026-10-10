from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=694,
    version="0.139.0",
    date="2026-10-09",
    title="Failed channels get re-checked again",
    items=(
        "Channels that failed to play are re-checked in the background whenever "
        "nothing is playing — an idle player window no longer blocks the check "
        "for the whole session.",
    ),
    test_steps=(
        "Play something, then close the stream (leave the app open) — within a few "
        "minutes the log says 'playback idle — probes resume' once, instead of "
        "'probe deferred' every 2 minutes.",
    ),
)
