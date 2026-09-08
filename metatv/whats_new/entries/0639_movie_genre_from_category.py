from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=639,
    version="0.105.0",
    date="2026-09-08",
    title="Movie genre chips actually find movies now",
    items=(
        "Clicking a genre chip (Horror, Thriller, …) in the details pane "
        "returned only a handful of titles out of a library of hundreds of "
        "thousands — almost all of them series, no movies. The provider's "
        "movie listings never carry a genre field at all (only its series "
        "listings do), so every movie's stored genre came back empty even "
        "though its category label (\"HORROR/THRILLER\", …) named one.",
        "Movies now fall back to reading their genre off that category "
        "label when the provider gave no genre field directly — the same "
        "cross-walk that already turns categories into genre tags "
        "elsewhere in the app. A genre a title states directly always "
        "wins over this guess.",
        "Existing libraries are backfilled automatically on next launch.",
    ),
    test_steps=(
        "Open the details pane for a movie whose category names a genre "
        "(e.g. a HORROR/THRILLER category) but that previously showed no "
        "genre chip — a genre chip now appears.",
        "Click that genre chip — the movie now appears in the results, "
        "alongside any series that already matched.",
        "Open a movie whose provider category is generic (e.g. \"NETFLIX "
        "MOVIES\") — it still shows no genre chip, not a wrong one.",
    ),
)
