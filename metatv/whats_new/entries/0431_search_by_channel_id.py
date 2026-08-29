from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=431,
    version="0.54.0",
    date="2026-08-29",
    title="Search finds a channel by its ID",
    items=(
        "Pasting a channel ID into the search box now finds that channel, so "
        "an exact reference can be noted down or passed to someone else.",
        "Both forms work: the app's own ID, and the plain stream ID the "
        "source itself uses.",
        "A stream ID finds that channel on every source carrying it, which is "
        "useful for comparing copies.",
        "IDs match exactly, so searching for a year or a number does not drag "
        "in unrelated channels.",
    ),
    test_steps=(
        "Copy a channel's ID from the details pane or a log line, paste it "
        "into search, and confirm that channel appears.",
        "Try the shorter stream ID on its own.",
        "Search for an ordinary word and confirm results are unchanged.",
        "Search for a year such as 2024 and confirm you get title matches, "
        "not random channels.",
    ),
)
