from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=16,
    version="0.7.0",
    date="2026-06-21",
    title="Source refresh shows a step-by-step checklist",
    items=(
        "The 'Refreshing {source}' toast now shows a labeled checklist — Fetching channels, Storing channels, Parsing & detecting — instead of an opaque progress bar.",
        "Sources with EPG enabled show two additional steps: Downloading EPG and Parsing EPG.",
        "Each step shows its status at a glance: pending (◻), active (⟳), or done (✓).",
    ),
)
