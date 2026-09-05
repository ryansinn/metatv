from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=598,
    version="0.97.0",
    date="2026-09-05",
    title="Record a channel for a time window",
    items=(
        "Any live channel can now be recorded for a time window you set "
        "yourself — no guide needed, so it works on sources with no EPG.",
        "Start/end padding is prefilled from Settings ▸ Recording and "
        "adjustable per recording.",
        "MetaTV says up front that it must stay open to record, and that "
        "recording will take the source's one connection.",
    ),
    test_steps=(
        "Right-click a live channel → \"Record for a time window…\" → set "
        "19:00–22:00 → it appears in the Recordings section with the "
        "padded window.",
        "Set an end time before the start time → OK is disabled and the "
        "dialog says why.",
    ),
)
