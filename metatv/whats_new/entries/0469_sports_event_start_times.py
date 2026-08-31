from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=469,
    version="0.60.0",
    date="2026-08-31",
    title="Sports fixtures now know when they start",
    items=(
        "Most sports fixtures had no start time, so they could not be sorted "
        "by when they are on, could not show a countdown, and could not be "
        "checked against the clock.",
        "Providers write the date three different ways. MetaTV understood one "
        "of them — 654 of the 1,358 fixtures in a typical library. It now "
        "reads all three, so every dated fixture gets a time.",
        "One of those formats gives the time in local time and names the zone "
        "— \"Sat 29 Aug 14:00 CEST\". Nearly 9 in 10 of those are not GMT, so "
        "reading them as GMT would have put them one to four hours out while "
        "looking perfectly normal. The zone is now converted properly.",
        "That format also leaves the year off. The day name is used to work it "
        "out, which pins it exactly rather than guessing.",
        "The bigger gap was that fixtures filed under Sports — as opposed to "
        "pay-per-view — never had their time read at all, even when it was "
        "sitting in the name. That is 927 more fixtures with a real start time.",
        "Your existing library is updated in place on the next launch; you do "
        "not need to refresh your sources.",
    ),
    test_steps=(
        ("Open Sports and sort or scan by time — fixtures should show real "
         "start times, not blanks.", "view:sports"),
        ("Open Events and confirm countdowns appear on fixtures that "
         "previously had none.", "view:events"),
        "Find a fixture whose name contains a zone such as CEST or EDT and "
        "check the time shown matches your own clock, not one shifted by a "
        "few hours.",
        "Confirm a 24/7 channel like Fox Sports 1 still shows no start time — "
        "it genuinely has no schedule, and inventing one would be wrong.",
        "Restart the app once and confirm the one-time update runs without "
        "blocking the interface.",
    ),
)
