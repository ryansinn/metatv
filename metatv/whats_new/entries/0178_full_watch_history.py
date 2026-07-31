from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=178,
    version="0.14.0",
    date="2026-07-31",
    title="Full Watch History — explore everything you've watched",
    items=(
        "The History sidebar section has a new 'See all →' link. It opens a full "
        "Watch-History view built on the same Explore trail-map: the left column is "
        "everything you've watched, most-recent first, and each row shows its poster, "
        "title/year, how many times you watched it and when ('watched 3× · yesterday'), "
        "plus the usual watched / partly-watched badges.",
        "History is a record of what you watched, so it shows titles even from sources "
        "you've since disabled or removed — nothing you played disappears from your "
        "history.",
        "Expand any history stop to fan out its similar titles in the next column and "
        "keep drilling sideways, exactly like Explore. The similar columns still "
        "respect your active sources, so suggestions only point at things you can "
        "actually play.",
        "The bottom detail strip tracks the selected title with a single Play / "
        "Resume M:SS / Play again button, favourite star, ratings and quick actions — "
        "so you can jump straight back into anything you were watching.",
    ),
    test_steps=(
        "In the sidebar History section header, click 'See all →': a full-window "
        "'Watch History' view opens with a left column listing your recently-watched "
        "titles, most-recent first.",
        "Confirm each history row shows a watch count and when you last watched it "
        "(e.g. 'watched 2× · 3d ago') and the correct watched / partly-watched badge; "
        "a title you played on a now-disabled source still appears.",
        "Click a history row to expand it: a 'SIMILAR TO <title>' column appears; click "
        "one of those and a further column cascades — the title you came from is not "
        "repeated (no loops).",
        "Select a partly-watched title and confirm the bottom strip's big button reads "
        "'Resume M:SS'; a completed one reads 'Play again'; click it to play.",
        "Click the ✕ in the header (or switch to another view via the bottom nav): the "
        "history view closes and returns to Browse without leaving a blank pane.",
    ),
)
