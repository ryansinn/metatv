from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=233,
    version="0.20.0",
    date="2026-08-02",
    title="Channel list now counts and reveals channels held back by repeated play failures",
    items=(
        "Channels whose reliability has graduated to \"dead\" (repeated play "
        "failures) were silently dropped from the channel list with no way to "
        "see how many or why. The filter-transparency bar above the channel "
        "list now gets a third segment — \"⚠ N unavailable (repeated play "
        "failures) — show\" — alongside the existing Global Exclusions and "
        "search-filter segments, so this layer is counted and recoverable "
        "instead of invisible.",
        "Clicking the new segment reveals those channels for the current view "
        "only (nothing is deleted or unhidden permanently); they keep their "
        "existing degraded/dim styling. The next search or filter change "
        "restores the default view.",
    ),
    test_steps=(
        "Find or create a channel with reliability_state 'dead' (repeated play "
        "failures) that would otherwise not appear in the channel list. Load "
        "the channel list — confirm it does not appear, and the gold "
        "filter-transparency bar shows a \"⚠ N unavailable (repeated play "
        "failures) — show\" segment.",
        "Click the ⚠ segment — the channel appears in the list with its "
        "existing degraded/dim styling. Change the search text or a filter — "
        "confirm the view reverts to hiding it again.",
    ),
)
