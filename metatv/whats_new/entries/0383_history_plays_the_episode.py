from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=383,
    version="0.41.0",
    date="2026-08-26",
    title="Double-clicking a History row plays the episode it names",
    items=(
        "A series row in History shows the episode you last watched. "
        "Double-clicking it now plays that episode. It used to work out a "
        "resume target from the series instead, and when the episode was "
        "finished with nothing after it there was no target at all - so the "
        "double-click opened the series browser and played nothing.",
        "Single-click still opens the details panel, and the skip-next button "
        "on the row still plays the NEXT episode - that button is asking a "
        "different question and is unchanged.",
        "A series you have never started still falls back to the resume "
        "ladder, which is the right answer when no row names an episode.",
    ),
    test_steps=(
        "Play an episode of a series to the end so it is marked complete, then "
        "find it in History - the row should show its S..E.. code.",
        "Double-click that row. It must play THAT episode, not open the series "
        "browser.",
        "Single-click the same row - the details panel opens as before.",
        "Click the skip-next button on the row - it must still play the next "
        "episode, not the one the row names.",
        "Double-click a movie or live channel in History - it plays as before.",
        "Double-click a series row for a show you have never played - it "
        "should still open the series view, since no episode is named.",
    ),
)
