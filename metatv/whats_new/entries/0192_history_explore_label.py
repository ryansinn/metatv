from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=192,
    version="0.15.0",
    date="2026-07-31",
    title="History: 'See all' is now 'Explore'",
    items=(
        "The sidebar History section's link is now labelled 'Explore →' instead of "
        "'See all →' — it opens the cascading-columns trail-map, which is about "
        "exploring outward from what you've watched, not just listing it.",
    ),
    test_steps=(
        "Open the sidebar History section header: the link on the right reads "
        "'Explore →' (not 'See all →'); clicking it opens the full Watch-History "
        "trail-map as before.",
    ),
)
