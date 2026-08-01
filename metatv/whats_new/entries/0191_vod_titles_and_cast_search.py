from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=191,
    version="0.15.0",
    date="2026-07-31",
    title="Cleaner movie titles + search now finds cast and directors",
    items=(
        "Movie titles that pack cast/extra credits after the year (e.g. "
        "'From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO, CHEECH MARIN') "
        "now parse to a clean title and a correctly captured year, instead of "
        "keeping the whole cast blob in the title and losing the year. This is "
        "a one-time data cleanup that runs automatically on launch.",
        "Search now also matches a title's director and cast, not just its name "
        "— searching 'Nicole Kidman' finds her movies even when the channel name "
        "itself doesn't mention her.",
    ),
    test_steps=(
        "Launch the app once so the one-time cleanup runs. Find a movie whose raw "
        "channel name had cast names trailing the year (e.g. anything like "
        "'... 4K (1996) ACTOR NAME, ACTOR NAME'); confirm its title now shows just "
        "the clean title and the year displays correctly (not blank).",
        "Search for an actor or director's name (e.g. an actor you know is in your "
        "library's metadata) and confirm movies/series featuring them appear in "
        "results even when their name isn't in the channel title.",
    ),
)
