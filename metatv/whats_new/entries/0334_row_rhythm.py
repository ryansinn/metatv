from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=334,
    version="0.41.0",
    date="2026-08-23",
    title="Channel rows keep one rhythm down the list",
    items=(
        "Two faults in the new row made a scrolling list feel uneven, both "
        "for the same underlying reason: something about a row's CONTENT was "
        "allowed to change its geometry.",
        "A row with nothing to put on its facts line dropped to a single line "
        "and re-centred its title, so titles stopped sharing a baseline and "
        "jumped up and down as you scrolled past a mix of rows.",
        "Live channels got shorter rows than movies and series, because a "
        "live channel's logo tile is square and the row was sized to its own "
        "artwork. A mixed list therefore stepped between two row heights.",
        "Rows are now one height throughout, and a title sits in the same "
        "place in every row whether or not it has anything beneath it. A "
        "square live tile centres inside the same row a poster gets.",
    ),
    test_steps=(
        "Open Search with no filters so the list mixes movies, series and "
        "live channels → every row is the same height, top to bottom.",
        "Find a row with a facts line (e.g. '2000 · Thriller / Drama') next "
        "to one with nothing beneath its title → both titles sit at the same "
        "height within their rows.",
        "Scroll quickly through a few hundred rows → the titles track a single "
        "straight line down the list with no stepping or jumping.",
        "Switch to a live-only view → those rows are the same height as the "
        "movie rows were, with the square logo tile centred in them.",
        "Settings → Interface → Channel List → Compact and Comfy+ → each "
        "density is internally consistent in the same way.",
    ),
)
