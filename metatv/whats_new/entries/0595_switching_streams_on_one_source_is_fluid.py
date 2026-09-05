from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=595,
    version="0.96.0",
    date="2026-09-05",
    title="Switching streams on the same source is fluid",
    items=(
        "Double-clicking another stream on the source you're already watching "
        "no longer re-probes it before playing — the stream that's currently "
        "playing is already proof the source is reachable, so the pre-flight "
        "check and failover cycle are skipped entirely.",
        "That switch now prefers whichever host is streaming right now, "
        "rather than re-resolving the source's URL order from scratch.",
        "On a one-connection source, a switch used to fail the first time and "
        "only work on a second click ~20 seconds later — the source kept "
        "counting the stream that had just closed. Retries now land every "
        "few seconds instead of waiting up to half a minute, and the app "
        "waits out a busy source and says what it's waiting for, instead of "
        "reporting a dead stream after 16 seconds.",
        "A stream that genuinely never opens is still reported as failed — "
        "just later (40 seconds instead of 16), so a slow-but-real retry "
        "isn't mistaken for one.",
        "mpv's own diagnostic messages (connection errors, reconnect "
        "attempts) now reach the app log instead of being silently discarded.",
    ),
    test_steps=(
        "Play a movie, then double-click another movie on the same source — "
        "it starts without a \"Stream did not start\" toast, and the status "
        "bar names the switch.",
        "Do the same with a live channel on the same source.",
        "Play a channel on a source that is genuinely offline — the failure "
        "toast still arrives, just later than before.",
    ),
)
