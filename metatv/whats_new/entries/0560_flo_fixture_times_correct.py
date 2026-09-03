from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=560,
    version="0.86.0",
    date="2026-09-03",
    title="FLO/FLSP fixture times are now read correctly",
    items=(
        "FLSP/flolive fixture times were parsed as UTC, but the provider's "
        "clock is actually US Eastern — a fixture listed 08:00 was really "
        "starting at 12:00 UTC, four hours later than the app showed. On "
        "Now / Upcoming for these rows is now truthful.",
        "Scoped strictly to the FLSP idiom: every other provider sharing "
        "the same timestamp grammar (ESPN+, Peacock, TSN+, VIX and others) "
        "is unaffected and stays read as UTC.",
        "Existing fixtures are corrected automatically at next launch via "
        "the sports reclassify pass.",
    ),
    test_steps=(
        "Find an FLSP fixture listed for later this evening — it now sits "
        "in Upcoming until its real (Eastern-converted) start time instead "
        "of showing early.",
        "The FLSP row that previously showed under 'On now' with a black "
        "pre-air slate in mpv no longer does — it now only appears live "
        "once the game has actually started.",
    ),
)
