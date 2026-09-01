from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=483,
    version="0.64.0",
    date="2026-08-31",
    title="Download a film from wherever you found it",
    items=(
        "Download only appeared when you right-clicked a film in the search "
        "results. The same film in Favorites, History, the Watch Queue, "
        "Recommendations, Discover or a Recipe had no way to download it.",
        "It is now on all of them. A right-click means the same thing "
        "everywhere, rather than depending on which list you happened to be "
        "looking at.",
        "Record now also appears on the EPG's On Now list, where the "
        "programme you are looking at is the one that gets recorded.",
        "Two places deliberately do not offer it: the retry list, where the "
        "stream already failed to open, and the EPG's forward guide, where "
        "recording a future programme needs a scheduler rather than a "
        "record-now button.",
    ),
    test_steps=(
        ("Right-click a film in Favorites and confirm Download to library is "
         "offered.", "view:favorites"),
        ("Do the same in History and the Watch Queue.", "view:history"),
        ("Right-click a card in Discover, and a result in Recommendations — "
         "both should offer it.", "view:discover"),
        "Right-click a LIVE channel in Favorites and confirm Download is NOT "
        "offered — there is nothing to download to.",
        "Right-click a programme in the EPG's On Now list and confirm Record "
        "is offered.",
    ),
)
