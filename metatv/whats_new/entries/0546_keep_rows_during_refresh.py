from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=546,
    version="0.82.0",
    date="2026-09-02",
    title="Channel list stays visible during background refreshes",
    items=(
        "After metadata enrichment settles, after provider changes, or when "
        "applying Global Exclusions, the channel list no longer blanks for "
        "several seconds while the new results are fetched — the old rows "
        "stay visible until the updated set arrives.",
        "A search or filter you initiate still clears to the loading state "
        "immediately, as before: old rows would misrepresent a NEW query, "
        "but a background refresh re-runs the same one.",
    ),
    test_steps=(
        "Apply Global Exclusions while the channel list is showing results: "
        "the list keeps its rows until the refreshed set appears — no "
        "multi-second blank flash.",
        "Type a new search: the list still clears to 'Loading channels…' "
        "immediately, as before.",
    ),
)
