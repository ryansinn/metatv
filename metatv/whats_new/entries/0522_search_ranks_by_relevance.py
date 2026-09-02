from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=522,
    version="0.70.0",
    date="2026-09-02",
    title="Search puts the thing you searched for first",
    items=(
        "Results were sorted alphabetically, so searching \"Tron\" returned 788 "
        "channels with \"24/7 The Astronaut Wives Club\" above \"Tron\" and the "
        "twelve exact matches nowhere to be found.",
        "Titles are now ranked: an exact match first, then titles starting "
        "with what you typed, then titles containing it as a whole word, then "
        "titles that merely contain the letters — and last, things that "
        "matched on cast or director rather than the title.",
        "Browsing is unchanged. The ranking only applies when you have typed "
        "something in the search box.",
    ),
    test_steps=(
        ("Search for a title you own that is also a common word fragment — "
         "\"Tron\" is a good one. The exact match should be the first result.",
         "view:list"),
        ("Confirm titles that merely contain the letters (Astronaut, "
         "Strongman, Voltron) now appear below every real title match.",
         "view:list"),
        ("Clear the search box and confirm the list is alphabetical again, "
         "exactly as before.", "view:list"),
        ("Search a cast member's name and confirm you still get their films — "
         "they now rank below title matches, which is a known step and is "
         "being addressed next.", "view:list"),
    ),
)
