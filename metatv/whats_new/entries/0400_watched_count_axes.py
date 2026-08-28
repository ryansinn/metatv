from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=400,
    version="0.52.0",
    date="2026-08-27",
    title="'N hidden because watched' counted things the list had already dropped",
    items=(
        "With Hide watched on, the stats label reports how many results are "
        "hidden for being watched. That number was worked out from a copy of "
        "your filters rather than the filters themselves.",
        "Three had gone missing from the copy: excluded keywords, the "
        "dead-stream filter, and the restricted set used by an alert's 'show "
        "matches'. So a watched title your keyword exclusions had already "
        "removed was still being reported as hidden-because-watched.",
        "The count is now given the same filters the list was given, instead "
        "of a hand-kept second copy of them.",
        "One limit stays, on purpose: a few exclusions are applied after "
        "results come back rather than in the query, and this count cannot see "
        "those. When one is active the number can still read slightly high - "
        "making it exact would mean running the whole search twice for a "
        "figure in a status line.",
    ),
    test_steps=(
        "Turn on Hide watched with a library where you have watched titles, "
        "and note the 'N watched hidden' figure in the stats label.",
        "Add a Global Exclusion keyword that matches one of those watched "
        "titles, then reload the list - the figure should drop by that title, "
        "not stay the same.",
        "Clear the keyword and confirm the figure returns to its earlier value.",
        "Turn Hide watched off and confirm the 'N watched hidden' text "
        "disappears entirely.",
    ),
)
