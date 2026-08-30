from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=453,
    version="0.58.0",
    date="2026-08-30",
    title="Series now show how long an episode runs",
    items=(
        "Your providers send an episode runtime with every series they list, "
        "and MetaTV was throwing it away — it only looked for the field movies "
        "use. Not one of the 652,216 titles in your library had a runtime "
        "stored, so the runtime slot in a title's details was always empty.",
        "It now reads the series field too. 48,322 series get a runtime.",
        "The rest genuinely have none: about 79,000 send a literal \"0\", "
        "which is a provider's way of saying \"unknown\". Those stay blank "
        "rather than claiming a zero-minute episode.",
        "Titles you already have are filled in by a one-time pass on the next "
        "launch, shown as \"Reading episode runtimes\". Anything refreshed "
        "from here on gets it as it arrives.",
    ),
    test_steps=(
        ("Launch MetaTV and watch the startup migration panel — a step named "
         "\"Reading episode runtimes\" should appear and complete.", "view:browse"),
        ("Open a series in the details pane. Where the runtime sits beside "
         "year and rating, it should now show a value in minutes instead of "
         "nothing.", "sample:series"),
        "Open several more series. Roughly one in three should show a runtime; "
        "the others should show NOTHING in that slot — never \"0 min\".",
        ("Open a movie and confirm its runtime behaviour is unchanged — movies "
         "get theirs from the separate per-title lookup, not from this.",
         "sample:vod"),
        "Quit and relaunch. \"Reading episode runtimes\" must NOT run a second "
        "time, and the runtimes you saw must still be there.",
    ),
)
