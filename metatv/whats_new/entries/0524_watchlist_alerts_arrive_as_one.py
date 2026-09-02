from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=524,
    version="0.70.0",
    date="2026-09-02",
    title="Watchlist alerts arrive together instead of one at a time",
    items=(
        "Shows on your watchlist are checked every minute, and every match "
        "raised its own pop-up. Television being television, they mostly "
        "start on the hour and half hour — so seven shows starting at 1:30 "
        "meant seven notifications landing in the same second.",
        "Now everything found in one check arrives as a single alert: "
        "\"7 shows starting in 15 min\", naming the first few. Alerts that "
        "are genuinely minutes apart still come separately, because they are "
        "not a burst.",
        "A single show is unchanged — it still names the show, the channel "
        "and how long you have.",
    ),
    test_steps=(
        ("Put several shows that start at the same time on your watchlist, "
         "then wait for the 15-minute mark before they start. You should get "
         "ONE notification naming the count, not one per show.", "view:list"),
        ("Confirm it names the first few shows and says \"and N more\" for "
         "the rest.", "view:list"),
        ("Watchlist a single show and confirm its alert is unchanged — the "
         "show name, the channel, and how many minutes away it is.",
         "view:list"),
    ),
)
