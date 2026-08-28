from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=404,
    version="0.53.0",
    date="2026-08-28",
    title="Watch Alerts could close the app about half a minute after a hiccup",
    items=(
        "Watch Alerts repaints every 30 seconds so 'in 5 min' stays honest as "
        "the clock moves.",
        "If the EPG list had just shown a message instead of programmes - "
        "'Loading', 'Nothing airing', or a load error - the rows it had been "
        "tracking were already gone, but it kept pointing at them. The next "
        "repaint reached for one and the app closed immediately.",
        "The list now lets go of those rows at the moment it replaces them, so "
        "the repaint has nothing stale to reach for.",
        "Reported from a real session, and the fix is covered by a test that "
        "reproduces the same crash on the old code.",
    ),
    test_steps=(
        "Open Watch Alerts with EPG alerts configured and let it populate.",
        "Force the EPG list into a message state - collapse and expand the "
        "section, or refresh while the guide is loading - so it shows "
        "'Loading' or 'Nothing airing'.",
        "Leave the app open for at least a minute without touching it. It "
        "should stay running; before this it closed on the next repaint.",
        "Confirm the Upcoming heading still shows its countdown chip when "
        "collapsed, and that the time updates as the clock moves.",
    ),
)
