from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=65,
    version="0.9.0",
    date="2026-06-24",
    title="New 'Category' facet for live channels (Sports/News/Kids/Adult/Music…)",
    items=(
        "A new 'Category' facet now correctly labels live channels by programming kind — "
        "Sports, News, Kids, Adult, Music, Religious, 24/7 — instead of incorrectly "
        "filing them under Language or Platform.",
        "The same values route to 'Genre' for movies and series (a sports movie is "
        "Genre: Sports; a live sports channel is Category: Sports).",
        "Pay TV is unaffected — it is a real distribution platform and remains "
        "under Platform.",
        "A one-time 'Re-faceting content-kind tags' migration runs at launch to "
        "correct all existing tags in your library.",
        "The Category facet is now visible in the Filter Panel, Recipe Builder "
        "(Pantry sidebar + recipe rail), and channel Details pane Tags section.",
    ),
    test_steps=(
        "Open the Filter Panel (left sidebar). Confirm a new 'Category' section "
        "appears between Quality and Genre listing values such as Sports, News, Kids.",
        "Check the Filter Panel Language section — confirm 'Adult' is no longer listed "
        "there (it moved to Category for live channels / Genre for movies).",
        "Check the Filter Panel Platform section — confirm 'Sports', 'Kids', 'Music', "
        "'News', 'Religious', '24/7' are no longer listed there.",
        "Select a live Sports channel and open its details pane. In the Tags section, "
        "confirm the tag reads 'Category: Sports' (not 'Platform: Sports').",
        "Select a sports movie and open its details pane. In the Tags section, confirm "
        "the tag reads 'Genre: Sports' (not 'Category:' or 'Platform:').",
        "Open the Recipe Builder (✦ chip). Confirm 'Category' appears in the Pantry "
        "sidebar. Click it and confirm live-channel kinds appear in the tag cloud.",
        "At launch (first run after update), confirm the 'Re-faceting content-kind tags' "
        "migration progress indicator appears and completes without error.",
    ),
)
