from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=384,
    version="0.41.0",
    date="2026-08-26",
    title="Cleanup: the search view's blank band, the UPCOMING heading, and the EPG count",
    items=(
        "The search view no longer has a strip of empty space above the "
        "Search row. The series Back/breadcrumb bar was taking a row in every "
        "view, not just the series one - its contents were hidden but the bar "
        "itself was not.",
        "The UPCOMING heading in Watch Alerts now lines up with the show "
        "titles below it, with its count in the space the play buttons "
        "occupy - so it reads as 9 UPCOMING instead of floating at an indent "
        "between EPG and the rows.",
        "The EPG count was one too high. It counted rows in the list rather "
        "than programmes, so the UPCOMING heading itself was being counted as "
        "a programme.",
        "Every view now starts with a slimmer strip of padding above it - "
        "about a quarter of what it was.",
        "The status line at the bottom no longer keeps the previous view's "
        "message. Switching from EPG to Discover used to leave the EPG "
        "programme count sitting under a page it had nothing to do with.",
    ),
    test_steps=(
        "Open the Search view. There should be no blank strip between the top "
        "of the panel and the Search row.",
        "Open a series, confirm the Back button and breadcrumb appear, then go "
        "back - the bar and its blank row should both disappear.",
        "In Watch Alerts, check the UPCOMING heading - the word should start "
        "at the same left edge as the show titles beneath it, with the count "
        "to its left.",
        "Add up the EPG group: shows on now plus the UPCOMING count should "
        "equal the number beside EPG exactly.",
        "Collapse UPCOMING and check the EPG number does not change - it "
        "counts programmes, not visible rows.",
        "Switch between views - the gap above each one should be small and the "
        "same in all of them.",
        "Open EPG so the status line shows its programme count, then switch to "
        "Discover - the line must go blank, not keep the EPG message.",
    ),
)
