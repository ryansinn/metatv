from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=389,
    version="0.41.0",
    date="2026-08-27",
    title="The channel list opens instantly",
    items=(
        "Browsing the channel list took about a quarter of a second per page, "
        "and roughly six-tenths of a second once you had scrolled a long way "
        "in. It is now about a millisecond, measured on a 492,000-channel "
        "library.",
        "The database had 33 indexes and not one of them fitted the query the "
        "app runs most, which filters on two columns and sorts on a third. "
        "Three new ones cover it, so the page arrives already in order instead "
        "of the whole library being sorted to return fifty rows.",
        "Counting, searching and filtering by source got the same treatment: "
        "181ms to 10ms, 279ms to 13ms, 228ms to 1.5ms. Favorites went from "
        "183ms to under a millisecond.",
        "On first launch after this update you will see a short 'Building "
        "channel indexes' step. It runs in the background and takes about "
        "thirteen seconds on a 492,000-channel library. It runs once.",
    ),
    test_steps=(
        "Launch the app. The Migration Center should show 'Building channel "
        "indexes' briefly, then move on to the other tasks.",
        "Open the channel list on Movies - the first page should appear "
        "without a visible pause.",
        "Scroll several thousand rows in - paging should stay fast rather "
        "than getting slower the deeper you go.",
        "Switch the media type to Series, then to Live, then to the unfiltered "
        "view - each should be equally quick.",
        "Type a search term - results should arrive without a stall.",
        "Open Favorites. This is the one that would REGRESS if the statistics "
        "step were skipped, so confirm it opens instantly rather than pausing.",
        "Close and relaunch. The 'Building channel indexes' step must NOT run "
        "a second time.",
    ),
)
