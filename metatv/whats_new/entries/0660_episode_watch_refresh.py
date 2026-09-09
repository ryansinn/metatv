from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=660,
    version="0.118.0",
    date="2026-09-09",
    title="The episode list now keeps up with what the queue marks watched — and \"No\" means no",
    items=(
        "When a queue auto-advanced through episodes, each one was marked "
        "watched in the database while the open season list carried on showing "
        "the state it was drawn with. The list now re-reads and repaints the "
        "affected rows — and the season's own ✓ / ◐ rollup with them — the "
        "moment the watch state is written, so what is on screen and what is "
        "stored can no longer disagree.",
        "This is what produced seasons with an unwatched gap in the middle of a "
        "watched run: the stale list showed only some of the auto-marked "
        "episodes, marking those unwatched left the invisible ones marked, and "
        "the gap only appeared on the next visit to the series.",
        "Answering \"No\" to \"Did you watch them?\" after an auto-advance run "
        "now unmarks those episodes. It previously left every one of them "
        "flagged watched and only rendered them in the dimmer queue colour — "
        "the opposite of the answer given.",
        "Marking an episode unwatched now also clears how it was played, so a "
        "row cannot come back watched-looking the next time the series is "
        "opened.",
    ),
    test_steps=(
        "Open a series, play an episode with the queue on, and let it "
        "auto-advance past at least one more episode. Leave the series list "
        "open while it plays — the finished episodes' glyphs update in place, "
        "without leaving and re-entering the series.",
        "In the same run, watch the season row: its rollup glyph moves from "
        "none/◐ to ◐/✓ as episodes complete.",
        "Close the player so the \"Still watching?\" prompt appears, and answer "
        "No — the auto-advanced episodes go back to unwatched immediately in "
        "the open list, and are still unwatched after leaving and re-opening "
        "the series.",
        "Repeat and answer Yes — the episodes stay watched and render in the "
        "solid (manual) style.",
        "Right-click an episode already marked watched → Mark as Unwatched, "
        "then leave the series and open it again: it is still unwatched.",
    ),
)
