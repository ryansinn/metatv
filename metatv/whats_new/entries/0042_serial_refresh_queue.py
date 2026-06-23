from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=42,
    version="0.9.0",
    date="2026-06-22",
    title="Serial source-refresh queue",
    items=(
        "Source refreshes now run one at a time instead of all at once — "
        "eliminates database contention and notification overflow when refreshing multiple sources.",
        "A single consolidated 'Source refresh queue' notification shows all sources with their "
        "status (queued / refreshing / done) instead of a separate toast per source.",
        "The detailed step-checklist toast (Fetching / Storing / Parsing / EPG) still appears "
        "for whichever source is actively refreshing — it advances as each step completes.",
        "Adding a source to the queue while another is running appends it — no duplicate "
        "overview notifications.",
    ),
)
