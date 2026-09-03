from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=579,
    version="0.93.0",
    date="2026-09-03",
    title="FloSports events are now captured under their real sports",
    items=(
        "FloSports vertical titles ('flofootball:', 'flovolleyball:', "
        "'floracing:', 'flograppling:', 'floswimming:', 'flotrack:', "
        "'flowrestling:', …) now classify to their sport instead of falling "
        "out of the Sports view — whole-token matching correctly refused to "
        "see 'football' inside 'flofootball', which left 1,370 of 1,960 FLSP "
        "rows unlabeled.",
        "Volleyball, Swimming and Track are new sports with their own chips "
        "and icons.",
        "A '| wrestling: …' title now passes the Sports gate too — it was "
        "already a keyword in the sport map but missing from the separate "
        "gate set.",
        "A one-time repair pass at next launch re-classifies the affected "
        "events.",
    ),
    test_steps=(
        "Open Sports after the launch repair completes → Volleyball / "
        "Swimming / Track chips exist and FLSP flofootball events sit under "
        "NFL-family football, floracing under Racing.",
        "The Tennis chip contains no flo-vertical or wrestling events.",
    ),
)
