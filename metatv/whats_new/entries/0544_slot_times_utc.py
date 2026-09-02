from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=544,
    version="0.82.0",
    date="2026-09-02",
    title='Sports "On now" was six hours off for baseball and other slot fixtures',
    items=(
        "The provider's start:/stop: slot times (MLB PACKAGE and similar) are "
        "UTC, and were being read as machine-local — so on the owner's "
        "machine every stored window was six hours later than the game "
        "actually was, games sat under \"Upcoming\" all evening, and \"On "
        "now\" only lit up around 3 AM.",
        "Fixed at the source: the slot-form parser now reads those times as "
        "UTC, matching every other event-time form in the app.",
        "Existing fixture rows re-derive their stored times automatically at "
        "the next launch — no source refresh needed.",
    ),
    test_steps=(
        "During a real MLB game window (evening US time), open Sports → On "
        "now: tonight's baseball fixtures are listed there, not under "
        "Upcoming.",
        "Check a fixture row's times against the provider's own start:/stop: "
        "values in the channel name: they match, with no hour shift.",
        "Restart the app once after updating: existing fixture rows "
        "re-derive their times (the migration runs at launch) without a "
        "source refresh.",
    ),
)
