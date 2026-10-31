from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=771,
    version="0.207.0",
    date="2026-10-31",
    title="Finished events are hidden",
    items=("Sources keep listing a game after it's over, with the name starting \"End |\" or "
           "\"ENDED |\". Those are now hidden everywhere, the same way Global Exclusions hide "
           "things, and counted in the \"hidden by exclusions\" note.",
           "To see them, open Global Exclusions and untick \"Hide finished events\" — or pause "
           "Global Exclusions, which shows everything.",),
    test_steps=("Search for \"End |\" or \"ENDED |\" — no finished-event channels appear, and the "
                "list's \"hidden by exclusions\" note counts them.",
                "Open Global Exclusions — \"Hide finished events\" is ticked, under \"Hide content "
                "with no category label\". Untick it and save — the search now lists them.",
                "Tick it again and save — they're hidden again.",
                "With nothing else excluded, the Exclusions chip in the header stays inactive.",),
)
