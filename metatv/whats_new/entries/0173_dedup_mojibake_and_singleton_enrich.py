from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=173,
    version="0.13.0",
    date="2026-07-31",
    title="Cleaner titles + wider TMDb matching — fewer duplicate movies/series",
    items=(
        "Some provider titles arrived with a stray, invisible \"junk\" character "
        "(a text-encoding artifact) that both showed as a little box in the name AND "
        "quietly split the movie from its other copies. These characters are now "
        "scrubbed out of the stored title, so the name reads cleanly and the copy "
        "lines up with its siblings.",
        "A one-time cleanup pass re-scrubs every already-imported title and "
        "recomputes its match key — only auto-derived fields are rewritten; your "
        "favorites, ratings, tags and history are never touched.",
        "Opening a movie or series with no listed \"Other Versions\" now still asks "
        "the source for its TMDb id in the background. Previously only titles that "
        "already had siblings were checked, so a lone copy could sit unmatched "
        "forever; now every title you look at gets a chance to link up and collapse "
        "onto one card.",
    ),
    test_steps=(
        "Find a movie whose title used to show a stray box/blank glyph (e.g. a "
        "Spanish \"Alita: Ángel de combate\" import): its details/title now display "
        "cleanly with no junk character.",
        "Open the details of an idless movie that has no \"Other Versions\" listed: a "
        "background \"Updating N titles from <source>…\" toast may appear as the app "
        "attempts to fetch its TMDb id (it did not before for a lone title).",
        "After the one-time \"Cleaning channel title qualifiers\" migration runs on "
        "launch, browse to a previously-corrupted title and confirm the name is clean "
        "and it groups with its other-language/quality copies where a TMDb id exists.",
    ),
)
