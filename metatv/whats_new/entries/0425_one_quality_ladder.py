from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=425,
    version="0.54.0",
    date="2026-08-29",
    title="Discover and the channel list agree on which copy is best",
    items=(
        "When a title had several copies, the two views could pick different "
        "ones to show you.",
        "Discover used its own quality ranking, which put HDR above HD and "
        "treated 8K and 4K as equally good.",
        "Both now use the app's single quality ranking, so the copy you see "
        "is the same wherever you look.",
        "HDR describes colour range rather than resolution, so it no longer "
        "outranks an HD copy on that basis alone.",
    ),
    test_steps=(
        "Find a title with several copies of differing quality. Note which "
        "copy the channel list shows.",
        "Find the same title in Discover or a recipe shelf and confirm it "
        "shows the same copy.",
        "Confirm a 4K copy still wins over FHD and HD.",
    ),
)
