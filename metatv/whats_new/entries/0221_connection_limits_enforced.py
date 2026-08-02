from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=221,
    version="0.19.0",
    date="2026-08-01",
    title="Per-source connection limits are now enforced",
    items=(
        "Sources with a simultaneous-stream limit (e.g. 1 or 2 connections) "
        "are now actually enforced when opening a second player window for "
        "the same source — previously the limit was tracked but never checked.",
        "If a play would exceed the source's connection limit, a warning now "
        "explains which source is at capacity and offers \"Play anyway "
        "(replace oldest)\" to close the oldest window and continue, or Cancel.",
    ),
    test_steps=(
        "Set a source's Max Connections to 1 in the provider editor, play a "
        "channel from it, then use \"Play in New Window\" on another channel "
        "from the same source — a \"Connection Limit Reached\" warning appears "
        "naming the source.",
        "Click \"Play anyway (replace oldest)\" on that warning — the oldest "
        "window closes and the new stream plays.",
        "With Max Connections left at the default, normal single-window "
        "playback across sources is unaffected.",
    ),
)
