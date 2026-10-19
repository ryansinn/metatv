from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=731,
    version="0.168.0",
    date="2026-10-19",
    title="Details: an episode says which episode it is; tidier title rows",
    items=("Selecting an episode now puts a small line above its title: \"SEASON 2 · EPISODE 1 "
           "OF 12\", with the air date at the right of the same line in your date format. The "
           "episode's own rating sits at the right of its title, written \"7.4 / 10\" like the "
           "series rating.",
           "The genre chips start at the left edge like every other row (they were indented), "
           "and the rating with its TMDb/IMDb chips moved up to the right end of the genre row.",
           "The source chip (and the collection chip beside it) moved to the right end of the "
           "\"Series · 2024\" line instead of taking a row of its own."),
    test_steps=("Open a series and select an episode in the tree — above the episode title a "
                "small line reads \"SEASON n · EPISODE n OF n\" (the total matches the season's "
                "episode count in the tree), with \"AIRED <date>\" at its right; the episode's "
                "rating, if it has one, sits at the right of the title.",
                "Look at any movie or series — the genre chips line up with the title's left "
                "edge, the rating and TMDb chip are at the right of the genre row, and the "
                "source chip is at the right of the \"Movie · 2024\" line."),
)
