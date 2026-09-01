from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=510,
    version="0.66.0",
    date="2026-09-01",
    title="Channels your source has dropped are finally removed",
    items=(
        "MetaTV added channels on every refresh and never removed any. Sources "
        "that reuse event slots — a new stream for each fixture — left the old "
        "one behind for ever. On a real library that was 1,960 rows for 980 "
        "actual channels, exactly two of everything, which is why the Sports "
        "'Channels' count looked so much bigger than the channels you have.",
        "A refresh now clears out what the source has stopped listing. Anything "
        "you have favourited, played or queued is kept regardless — it stays in "
        "History and Favourites as before.",
        "If a source answers with far less than usual — a bad connection rather "
        "than a real change — nothing is removed at all, and the reason is "
        "written to the log. A truncated answer must never look like a shrunken "
        "library.",
    ),
    test_steps=(
        ("Refresh a source and confirm it completes normally.",
         "view:browse"),
        ("Check the log for 'pruned N channel(s) the source no longer lists' — "
         "or for the refusal message if the source returned much less than "
         "usual."),
        ("Open Sports and confirm the 'Channels' count is lower and closer to "
         "the number of real channels.", "view:sports"),
        ("Confirm your favourites are all still present after the refresh.",
         "view:browse"),
        ("Confirm Watch History still lists everything it did before, "
         "including anything the source has since dropped."),
    ),
)
