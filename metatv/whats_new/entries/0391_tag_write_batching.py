from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=391,
    version="0.41.0",
    date="2026-08-27",
    title="Refreshing a source spends far less time tagging",
    items=(
        "After every source refresh the app re-derives tags for the channels "
        "whose details changed. That pass was issuing four separate database "
        "statements for each channel; it now issues about four for each batch "
        "of five hundred.",
        "Measured over 20,000 channels: 44 seconds and 160,086 statements "
        "before, 7.5 seconds and 288 after. The tags written are identical - "
        "80,000 links either way.",
        "Two separate causes. The writes were done one channel at a time even "
        "though bulk versions already existed and the one-time migration "
        "already used them. And the tag-id cache, which is supposed to avoid "
        "database lookups, was doing one per tag per channel anyway.",
    ),
    test_steps=(
        "Refresh a source with a large catalog and watch the log for "
        "'computing tags for N channels' - the pass should finish noticeably "
        "sooner than before.",
        "Open the filter panel afterwards and confirm the tag facets "
        "(language, quality, platform, genre) still list the same values with "
        "sensible counts.",
        "Right-click a channel and check its tags are present and correct - "
        "the point of this change is that nothing about the tags changes.",
        "Add a user tag to a channel, then refresh that source again - the "
        "user tag must survive; only generated tags are rebuilt.",
        "Refresh the same source a second time with nothing changed - it "
        "should skip almost everything and finish very quickly.",
    ),
)
