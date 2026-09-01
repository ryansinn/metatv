from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=509,
    version="0.65.0",
    date="2026-09-01",
    title="Sports rows showed last week's fixture, and your saved sport was ignored",
    items=(
        "Event channels get reused: the slot carrying a volleyball match last "
        "Thursday carries a hockey game tonight. MetaTV was updating the "
        "channel but keeping the OLD fixture's title, so the list showed a "
        "game from days ago on a channel that was genuinely live — and the "
        "title in the player didn't match the title in the app. On a real "
        "library that was 1,077 of 2,940 dated events. They are all re-read "
        "once, automatically, on the next launch.",
        "The 'On now' list itself was right the whole time — those events "
        "really were on. Only the titles were stale.",
        "Your saved sport filter is now actually applied when MetaTV starts. "
        "It was being restored onto the buttons but never used for the list, "
        "so you would see (say) Baseball selected above a screen of hockey "
        "until you clicked the button off and on again.",
    ),
    test_steps=(
        ("Open Sports and confirm the fixture titles match what is actually "
         "playing — compare a row against the player's own title.",
         "view:sports"),
        ("Confirm 'On now' rows show today's date rather than one from days "
         "ago."),
        ("Pick a single sport, quit MetaTV, and reopen it. Confirm the list "
         "is already filtered to that sport without touching anything."),
        ("Confirm the lane counts (On now / Upcoming / Channels) match the "
         "filtered sport rather than the whole library."),
        ("Clear the sport filter, restart, and confirm everything is shown "
         "and nothing was lost."),
        ("Watch the first launch for the 'Cleaning channel title qualifiers' "
         "migration step, and confirm it completes."),
    ),
)
