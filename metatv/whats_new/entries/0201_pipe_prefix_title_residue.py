from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=201,
    version="0.16.0",
    date="2026-08-01",
    title="Fixed: stray '. ' at the start of some movie & series titles",
    items=(
        "Providers that name entries like '|MULTI|. Spider-Man: Far from Home' "
        "left the '. ' separator behind after the |MULTI| prefix was stripped, so "
        "titles displayed (and sorted) with a leading dot. The parser now removes "
        "separator punctuation left over from a prefix strip — while titles that "
        "genuinely start with punctuation (like '.hack//Sign') are untouched.",
        "Already-imported titles are re-parsed automatically once on next launch "
        "(the same one-time pass also refreshes their dedup identity).",
    ),
    test_steps=(
        "Launch the app after updating and let the one-time re-parse finish "
        "(background; large libraries take a moment).",
        "Search for a title that previously displayed as '. Something' (e.g. the "
        "affected Spider-Man entry) → it now displays without the leading '. ' "
        "and sorts under its real first letter.",
        "Confirm a legitimately punctuation-led title (if your library has one, "
        "e.g. '.hack//Sign') still shows its leading dot.",
    ),
)
