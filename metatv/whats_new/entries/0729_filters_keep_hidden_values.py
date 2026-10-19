from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=729,
    version="0.166.0",
    date="2026-10-19",
    title="Filters you never set no longer appear on their own",
    items=("Language, Platform, Region and other filters could switch themselves on and show "
           "as chips over your searches without you choosing them. A value the filter panel "
           "wasn't showing at the time it saved — because Global Exclusions or a disabled "
           "source hid its titles — was forgotten as \"included\", so when it came back it "
           "came back switched off. The panel now keeps such a value as it was.",
           "Filters that already got stuck this way stay until you clear them once: click All "
           "at the top of the filter panel (or the clear-all chip). All now switches on every "
           "value, including ones the panel isn't showing right now."),
    test_steps=("Open the filter panel and click All — the filter chips above the list disappear "
                "and a search shows no Language or Platform chip.",
                "Add a language to Global Exclusions, close and reopen MetaTV, then remove it "
                "again and restart — that language is ticked in the filter panel and no "
                "Language chip appears."),
)
