from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=378,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts lists what has arrived, not everything you're watching for",
    items=(
        "The Watch Alerts sidebar section now shows only entries that have "
        "something new - a keyword rule with new matches, a series with new "
        "episodes. Rules and series that have not turned anything up are no "
        "longer listed there by default.",
        "Your full list has not changed and nothing was removed. It is in "
        "Manage Watch Alerts, and EPG keywords are in the EPG view's Watch "
        "tab.",
        "A new switch, \"Show alerts with nothing new\", brings the old "
        "behaviour back. It is in Settings - Interface - Watch Alerts AND in "
        "Manage Watch Alerts; both are the same setting, so they can never "
        "disagree.",
        "A COLLAPSED group heading now carries a solid \"+N\" chip counting "
        "what is new inside it - the same green pill the section header uses. "
        "Expanded, the rows carry their own markers, so the heading stays "
        "plain.",
        "If you have alerts set up and none of them is firing, the section "
        "says so rather than looking empty.",
    ),
    test_steps=(
        "Open the sidebar with some keyword rules and monitored series where "
        "only a couple have anything new. Only those few are listed under "
        "Movies and Series.",
        "Hover a group heading - the tooltip says how many are not being "
        "shown and where to turn them on.",
        "Collapse the Series group - its heading gains a solid green \"+N\" "
        "chip counting the new episodes inside. Expand it again and the chip "
        "goes away.",
        "Do the same with Movies.",
        "Settings - Interface - Watch Alerts - tick \"Show alerts with "
        "nothing new\" and click OK. Every rule and series is now listed.",
        "Open Manage Watch Alerts - its switch is already ticked, because it "
        "is the same setting. Untick it there; the sidebar updates "
        "immediately and Settings agrees next time you open it.",
        "With the switch off and nothing firing at all, the section shows a "
        "line reading \"Nothing new from N alerts\" rather than an empty box.",
        "Remove every alert - now the Movies and Series area disappears "
        "entirely, since there is nothing to report on.",
    ),
)
