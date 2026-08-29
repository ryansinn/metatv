from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=422,
    version="0.53.0",
    date="2026-08-29",
    title="The channel list loads about five times faster",
    items=(
        "Grouping a title's different copies into one row was the single "
        "biggest cost in loading the list - measured at 8.3 seconds on a large "
        "library.",
        "It was doing the grouping in a way that had to walk every row before "
        "it could pick winners, so asking for one screenful cost the same as "
        "asking for a thousand.",
        "It now groups as it reads. Same rows, same order, same counts - just "
        "over five times faster.",
        "Every search, filter change, exclusion toggle and source click was "
        "paying that cost, so the whole app should feel quicker.",
    ),
    test_steps=(
        "Load the channel list with variant grouping on and confirm it "
        "appears noticeably faster.",
        "Search, then change a filter, and confirm each is quicker than "
        "before.",
        "Confirm titles with several copies still show one row with the "
        "correct x N count, and the copy shown is still the best quality "
        "available.",
        "Scroll deep into the list and confirm no title is duplicated or "
        "missing at a page boundary.",
    ),
)
