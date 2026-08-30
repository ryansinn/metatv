from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=450,
    version="0.56.0",
    date="2026-08-29",
    title="History groups by when, and says which copy you watched",
    items=(
        "History showed the same thing twice: a list already in time order, "
        "with the time written again on every row. Meanwhile two copies of one "
        "film - a 4K you started and the HD you actually watched - looked "
        "identical, because nothing on the row said which was which.",
        "The time moved up into groups, the way a browser's history works: "
        "Last hour, Today, Yesterday, Earlier this week, Earlier this month, "
        "Older. Empty groups are not shown.",
        "The freed space went to quality, right beside the title where you "
        "compare two rows, with the language after the year.",
        "Each group heading has a delete button that forgets just that group - "
        "so clearing out last month no longer means clearing everything. The "
        "⋯ menu still has Clear all history.",
        "Two bugs turned up while building it. \"Clear history older than 30 "
        "days\" was comparing two different clocks and actually cleared 29.75 "
        "days - a little more than you asked, permanently. And the group "
        "boundaries disagreed with the delete ranges at the exact hour and day "
        "edges, which would have let a heading delete a row it never listed.",
    ),
    test_steps=(
        "Open History and confirm rows sit under time headings, newest first, "
        "with no empty groups.",
        "Find two entries for the same title at different qualities and "
        "confirm the quality chip beside each title tells them apart.",
        "Confirm the rows no longer show a per-row time like \"2h\".",
        "Click the delete icon on one group, confirm the prompt names that "
        "group, accept it, and confirm only that group's rows are gone.",
        "Confirm the ⋯ menu still offers Clear all history.",
        "Play something, return to History, and confirm it appears under Last "
        "hour.",
    ),
)
