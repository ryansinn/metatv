from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=200,
    version="0.16.0",
    date="2026-08-01",
    title="Right-click a title: 'Search this title' and 'Copy title'",
    items=(
        "'Search this title' jumps to the Search view with the title already in the "
        "search box — the quickest way to see every version of something you're "
        "looking at, across all your sources.",
        "'Copy title' puts the title on your clipboard, for pasting into a search "
        "engine, a note, or a message to someone.",
        "Both use the clean title MetaTV detected at import — 'The Matrix', not "
        "'EN ★ The Matrix (1999) [HEVC]' — so the search actually finds things. If a "
        "channel has no detected title, they fall back to its full name.",
        "Available on right-click in the channel list, History, Favorites, Watch "
        "Queue, Recommended and Watch Alerts.",
    ),
    test_steps=(
        "Right-click any movie in the channel list and choose 'Search this title'. "
        "Confirm the view switches to Search, the search box contains the clean "
        "title (no source prefix, quality tag or year), and the results list every "
        "version of it.",
        "Right-click the same title and choose 'Copy title', then paste into the "
        "search box (or any text field): the clean title is on your clipboard, and "
        "the status bar confirmed the copy.",
        "Right-click an item in Favorites, Watch Queue and History and confirm both "
        "actions appear there too and behave the same.",
        "Select several channels at once and right-click: neither action appears "
        "(they act on a single title only).",
    ),
)
