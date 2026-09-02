from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=530,
    version="0.72.0",
    date="2026-09-02",
    title="Filter the results you already have",
    items=(
        "A search that returns ninety things is still ninety things to read. "
        "There is now a \"Filter these results\" box on the filter line that "
        "narrows what is already listed, instantly, without going back to the "
        "provider.",
        "It matches anything on the row — the title, the person, the year, "
        "the genre, the category. Type \"cage 2024\" and you get the 2024 Cage "
        "film; the words can be in any order and can come from different "
        "parts of the row.",
        "It narrows the results in front of you rather than searching your "
        "whole library, which is why it is instant. Clear it and everything "
        "comes back. It is never remembered between sessions.",
    ),
    test_steps=(
        ("Search something broad, then type a word into \"Filter these "
         "results\". The list should narrow as you type, with no loading.",
         "view:list"),
        ("Type a YEAR, then a genre, then part of a person's name — each "
         "should narrow the list, since it matches the whole row.",
         "view:list"),
        ("Type two words that live in different parts of a row, like a name "
         "and a year, and confirm you still get the match.", "view:list"),
        ("Clear the box with its × and confirm every result returns.",
         "view:list"),
        ("Check the channel count follows the filter rather than reporting "
         "what was fetched.", "view:list"),
        ("Narrow the window until filter chips start collapsing and confirm "
         "the box is not squashing them off the line.", "view:list"),
    ),
)
