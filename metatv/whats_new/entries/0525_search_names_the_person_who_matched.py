from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=525,
    version="0.70.0",
    date="2026-09-02",
    title="Cast & Crew results say whose films they are",
    items=(
        "Searching a name put every match in one long Cast & Crew list, so "
        "eighty results for \"Cage\" gave no clue which were Nicolas Cage and "
        "which were a Beaucage or a McCager.",
        "The person is now named once, above their own films. On a real "
        "library those eighty resolve to 65 under Nicolas Cage, 4 under "
        "Weston Cage, 3 under Finn McCager Higgins — so a loose match is "
        "obviously loose, because its group is small and has a name on it.",
        "Films are regrouped under the right person rather than left in the "
        "order they were found, and the people stay in the order the search "
        "ranked them — the strongest match first, never alphabetical.",
        "A result that matched on cast but whose name could not be worked out "
        "still appears, above the named groups, without a heading.",
    ),
    test_steps=(
        ("Search for an actor's surname that several people share — \"Cage\" "
         "is a good one. Under Cast & Crew each person's name should appear "
         "ONCE, with their films beneath it.", "view:list"),
        ("Confirm the best-matching person is the first group, not whoever "
         "comes first alphabetically.", "view:list"),
        ("Check the Cast & Crew count in its heading matches the number of "
         "FILMS, not films plus names.", "view:list"),
        ("Click a person's name. Nothing should happen — it is a label, and "
         "the details pane must not change.", "view:list"),
        ("Scroll a long search to load more results and confirm no person "
         "gets a second heading further down the list.", "view:list"),
    ),
)
