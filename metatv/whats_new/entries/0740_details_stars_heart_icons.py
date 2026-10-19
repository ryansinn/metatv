from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=740,
    version="0.177.0",
    date="2026-10-19",
    title="Details pane: star ratings, a heart for favourites, clean icons",
    items=("Ratings in the details pane are five stars, a half star per point; hover them "
           "for the exact score and vote count.",
           "Favourite is a heart — filled pink when the title is a favourite.",
           "The action buttons use one clean icon set instead of emoji, and the live "
           "\"add to watchlist\" button no longer shares Watch Later's icon."),
    test_steps=("Select a movie with a rating — the details pane shows five gold stars "
                "(e.g. 7.4 shows three and a half); hover them — the tooltip reads "
                "\"7.4 / 10\" and the vote count when known.",
                "Click the heart — it fills pink with a pink border; click again — it "
                "returns to an outline heart.",
                "Look along the action rail — hide, like, not interested, dislike and the "
                "alert bell are single-colour icons, not emoji; Play, Resume, Watch Later "
                "and Trailer show an icon beside their words.",
                "Select a live channel — the watchlist button shows an alarm clock, "
                "Watch Later a bookmark."),
)
