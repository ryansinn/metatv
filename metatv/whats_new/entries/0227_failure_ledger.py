from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=227,
    version="0.19.0",
    date="2026-08-01",
    title="Unreliable streams now get called out — and hopeless ones get out of your way",
    items=(
        "A channel that keeps failing to play graduates through a reliability "
        "ledger: after a few failures it's shown grayed-out (but still "
        "clickable) in the channel list; after enough repeated failures it "
        "stops appearing in the list entirely instead of cluttering it forever.",
        "Streams that fail with an authentication/gating-style error (401/403/511) "
        "now also count toward this ledger — previously those were ignored, so a "
        "channel that always returned one of those codes never got flagged even "
        "though it never actually played.",
        "A stream that comes back online (confirmed by the background retry "
        "checker) is immediately restored to full visibility, however far it had "
        "degraded.",
        "New Settings toggle \"Re-check failed streams on source refresh\" "
        "(on by default) controls whether refreshing a source also re-probes "
        "its previously-failed streams right away.",
    ),
    test_steps=(
        "Repeatedly fail to play the same channel (or simulate via a bad URL) "
        "3+ times — it should start rendering grayed-out (but still playable) "
        "in the channel list.",
        "Keep failing the same channel to 6+ total failures — it should "
        "disappear from the channel list entirely.",
        "Let the background stream-retry checker confirm that channel is back "
        "online (or trigger a source refresh with the new toggle on) — it "
        "should return to normal, full-color, visible-in-list state.",
        "Open Settings → Playback and confirm the \"Re-check failed streams on "
        "source refresh\" toggle is present and defaults to on.",
    ),
)
