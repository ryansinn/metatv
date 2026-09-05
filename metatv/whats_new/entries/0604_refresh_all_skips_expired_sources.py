from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=604,
    version="0.99.0",
    date="2026-09-05",
    title="Refresh All skips expired sources",
    items=(
        "Refresh All no longer tries sources whose subscription has lapsed.",
        "Refreshing one source by hand still works — that is how a renewal "
        "is picked up.",
    ),
    test_steps=(
        "With an expired source in the list, click Refresh All — the log "
        "says it skipped that source and it is not refreshed.",
        "Refresh that source alone from its own button — it refreshes.",
    ),
)
