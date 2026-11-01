from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=793,
    version="0.229.0",
    date="2026-11-01",
    title="\"Hide finished events\" now hides games whose time has passed",
    items=("Fixture channels marked \"Ended\" (college games on FLO NETWORK and similar) are hidden while "
           "\"Hide finished events\" is on, not only the ones whose names start \"END |\". On this library "
           "that is about 2,600 finished slots.",),
    test_steps=("Search \"vs\" — no rows marked \"Ended\"; games on now and upcoming games still show.",
                "Open Exclusions, uncheck \"Hide finished events\", OK — the Ended rows come back.",),
)
