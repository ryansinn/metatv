from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=716,
    version="0.156.0",
    date="2026-10-10",
    title="Opening a series asks its source for details",
    items=("Opening a series' details now asks the source once (as movies already did), "
           "filling in missing cast, director, genres and backdrop.",),
    test_steps=("Open the details of a series on an Xtream source — the log shows "
                "'Provider details for … (series)' with what arrived; credits missing "
                "before now appear.",),
)
