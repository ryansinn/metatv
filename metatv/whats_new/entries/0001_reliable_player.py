from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=1,
    version="0.1.0",
    date="2026-06-19",
    title="A more reliable player",
    items=(
        "Streams now auto-reconnect after brief network drops instead of dying.",
        "Pick how much to buffer in Settings → Playback (reconnect-only, modest, or large).",
        "New optional 'pre-buffer before playing' — fills the buffer first for stutter-free movie starts.",
        "Diagnose a troublesome stream and apply its recommended tuning in one click.",
    ),
)
