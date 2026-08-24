from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=343,
    version="0.41.0",
    date="2026-08-24",
    title="Similar Titles: Play appears where the pointer is",
    items=(
        "Eighteen similar titles meant eighteen Play buttons down the left "
        "edge — a column of identical glyphs saying nothing, because every row "
        "can be played. Play now appears only on the row you are pointing at.",
        "Nothing moves when it appears: the button keeps its space while "
        "hidden, so the titles stay in a column instead of stepping sideways "
        "as the pointer runs down the list.",
        "Favourite and Queue stay visible. Those two say something about the "
        "title — a gold star you can only see by hovering is a star you cannot "
        "see. Play was the only one of the three carrying no state.",
    ),
    test_steps=(
        "Open a movie with similar titles → the Similar Titles rows show no "
        "Play buttons at rest; the list reads as titles, not as a column of ▶.",
        "Move the pointer onto one row → its Play button appears, and only "
        "that row's. The title text beside it does not shift.",
        "Move off the row → the Play button disappears again.",
        "Hover a row and click its Play button → that title starts playing, "
        "exactly as before.",
        "Favourite or queue one of the similar titles → the gold star / queue "
        "marker stays visible with the pointer well away from that row.",
    ),
)
