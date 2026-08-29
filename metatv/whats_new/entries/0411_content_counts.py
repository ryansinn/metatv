from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=411,
    version="0.53.0",
    date="2026-08-28",
    title="Sidebar counts stopped counting the labels as items",
    items=(
        "Favorites showed 2 with no favorites at all. The two lines telling you "
        "there are none - 'No favorites yet' and the hint under it - were being "
        "counted as favorites.",
        "The same thing inflated other sections: Watch Queue read 5 for three "
        "titles, because 'Continue watching' and 'Never watched' are rows too.",
        "Each of the four sections had its own copy of the count, and each "
        "skipped exactly one kind of label while counting the rest.",
        "There is now one rule, and it counts the things you can actually click "
        "rather than trying to list everything to ignore.",
    ),
    test_steps=(
        "On a profile with no favorites, confirm the Favorites header shows no "
        "count rather than 2.",
        "Add one favorite and confirm the header reads 1.",
        "Open Watch Queue with titles under group headings and confirm the "
        "count matches the number of titles, not titles plus headings.",
        "Check History and Recommended headers agree with what is listed.",
    ),
)
