from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=532,
    version="0.72.0",
    date="2026-09-02",
    title="\"On now\" reads the game's real end time instead of guessing four hours",
    items=(
        "Nothing was ever On Now for long. A fixture was treated as under way "
        "for a flat four hours after it started, and the provider's own MLB "
        "slots run 3 to 7 hours — so a game you were actually watching was "
        "filed under Finished about 45% of the way through.",
        "The end time was in the channel name the whole time. The provider "
        "sends \"start:… stop:…\" and only the start was ever read; the stop "
        "is now parsed and stored, and the Sports lanes and the Events "
        "countdown both use it.",
        "It was wrong in the other direction too. Slots shorter than four "
        "hours stayed listed as On Now after they had ended — and because the "
        "provider reuses the stream number, opening one played whatever was on "
        "that slot at the time rather than the game named on the row.",
        "Fixtures whose name carries no end time are unchanged: they still use "
        "the four-hour assumption, which is now defined in one place instead "
        "of three that could drift apart.",
        "Existing rows pick the end time up on the next launch — the sports "
        "re-sort runs once and fills it in.",
    ),
    test_steps=(
        ("Open Sports while a long fixture (an MLB slot) is more than four "
         "hours into its window. It must sit in On now, not Finished.",
         "view:sports"),
        ("Check the On now chip's count against the rows beneath it — the "
         "count and the list must agree.", "view:sports"),
        ("Find a fixture whose window has ended and confirm it has left On "
         "now for Finished.", "view:sports"),
        ("Open Events and confirm an under-way event still shows its elapsed "
         "time (\"2h 5m in\") past the four-hour mark, and stops when its "
         "window ends.", "view:events"),
        ("Confirm a 24/7 sports channel with no date is still listed under "
         "Channels and never claims to be on now.", "view:sports"),
    ),
)
