from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=380,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar groups stay how you left them, and sections give back the room they aren't using",
    items=(
        "Watch Alerts no longer closes its own groups when it runs short of "
        "height. Shrink the section and EPG, Movies, Series and Stream "
        "Monitoring all stay open - the content simply scrolls, which it "
        "always did. Folding hid rows without showing anything extra in "
        "return.",
        "This also fixes clicking a heading closing a DIFFERENT group. Opening "
        "Stream Monitoring used to silently collapse EPG to make room.",
        "A section that has less content than it has height now hands the "
        "surplus back. Watch Alerts used to hold its full height for three "
        "collapsed headings, so Recommended could not grow into the empty "
        "space below it.",
        "Collapsing a group yourself still works exactly as before, and now "
        "shrinks the section to match rather than leaving a gap where the rows "
        "were.",
        "Right-clicking an episode now offers Browse the Series, next to the "
        "like and dislike actions that already applied to the series rather "
        "than the episode.",
    ),
    test_steps=(
        "Open Watch Alerts with EPG expanded, then drag the handle below it "
        "upward to squeeze the section. EPG must stay open the whole way down "
        "- the rows scroll instead of disappearing.",
        "With the section short, scroll inside it: every group's rows are "
        "still reachable, nothing was hidden.",
        "Click the STREAM MONITORING heading to expand it. EPG must not close.",
        "Collapse EPG, Movies and Series yourself so only headings remain - "
        "Watch Alerts should shrink to fit them, and Recommended below it "
        "should grow into the space it released.",
        "Expand them again - Watch Alerts takes its room back and Recommended "
        "returns to its own size.",
        "Restart the app - the section sizes and your collapsed groups are "
        "both restored, and nothing re-opens or re-closes on its own.",
        "Right-click a watched episode in History and choose Browse the "
        "Series - the series opens in the channel list.",
        "Confirm Browse the Series sits beside the like/dislike actions in "
        "that menu, and does not appear when right-clicking a movie.",
    ),
)
