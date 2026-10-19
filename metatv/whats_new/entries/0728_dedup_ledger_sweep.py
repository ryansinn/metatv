from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=728,
    version="0.166.0",
    date="2026-10-19",
    title="Play All remembers movies, and \"See all\" names your own shelves",
    items=("Play All on a selection of movies now saves how far you got in each one, and "
           "marks a movie watched once the queue moves past it. Before, only episodes in a "
           "queue kept their place; a queued movie showed up in History but never got a "
           "resume point or a watched mark.",
           "Discover → \"See all\" on one of your own categories or saved recipes is headed "
           "by its name — the same title as the shelf, with the recipe ✦ — instead of an "
           "internal key such as \"user_cat:Comfort Watches\".",
           "The quality tooltip on a copy in Details uses the same words as the rest of the "
           "pane: \"Seen when played\", \"Probed\" or \"Reported by source\", with the date."),
    test_steps=("Select two movies in the channel list, right-click → Play All. Watch the "
                "first for a minute, press > in mpv to skip to the second, watch it for a "
                "minute, then close mpv — the first movie shows the watched mark in the list, "
                "and selecting the second offers Resume from about a minute in.",
                "In Discover, on a shelf from one of your categories (or a saved recipe), click "
                "\"See all\" — the heading is the category's name (the recipe keeps its ✦), not "
                "a \"user_cat:\" or \"recipe:\" key.",
                "Play a movie for a few seconds, then hover its copy chip in Details — the "
                "tooltip starts \"Seen when played <date>:\"."),
)
