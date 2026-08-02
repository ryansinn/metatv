from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=238,
    version="0.20.0",
    date="2026-08-02",
    title="Restricted-content filter now catches name-flagged channels too",
    items=(
        "The Adult content filter (Hide/Only) previously relied solely on the "
        "provider's adult-content flag — a channel named with an explicit "
        "marker (e.g. an XXX/ADULT prefix) that the provider failed to flag "
        "could still leak into Discover shelves, recommendations, and browse. "
        "Channel names/prefixes are now scanned at refresh time for the same "
        "explicit-content conventions, and any match is now caught by 'Hide "
        "adult' / 'Adult only' alongside the provider flag.",
    ),
    test_steps=(
        "With a channel named e.g. 'XXX Movies' whose provider does NOT flag it "
        "as adult, set the filter bar's Adult dropdown to 'Hide adult' → the "
        "channel no longer appears in the channel list. Switch to 'Adult only' "
        "→ the channel appears. Expand a Discover genre shelf that would "
        "otherwise include it → it is excluded under 'Hide adult' too.",
    ),
)
