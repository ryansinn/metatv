from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=14,
    version="0.6.0",
    date="2026-06-22",
    title="Refreshing a source now updates its EPG too",
    items=(
        "Refreshing a source pulls current guide data as a second step — no separate 'Refresh EPG' needed.",
        "Sources with EPG turned off are skipped automatically.",
    ),
)
