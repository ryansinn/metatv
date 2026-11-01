from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=795,
    version="0.231.0",
    date="2026-11-01",
    title="Finished PPV games stop showing as black-screen channels",
    items=("Numbered PPV slots such as \"(Apple) (MLS) 005 | Miami vs. Cincinnati (2026-10-28 19:25)\" now "
           "keep their game time, so once the game is over \"Hide finished events\" hides the slot instead "
           "of leaving a black screen in your results. Applied on the next launch.",),
    test_steps=("Launch MetaTV, search \"MLS\" — the 28 October slots (e.g. Miami vs. Cincinnati) are gone; "
                "upcoming games remain.",
                "Uncheck \"Hide finished events\" in Exclusions — they come back marked \"Ended\".",),
)
