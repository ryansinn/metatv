from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=60,
    version="0.9.0",
    date="2026-06-24",
    title="Genre tags for movies (from provider category)",
    items=(
        "Movies now receive genre tags derived from their provider category name "
        "(e.g. a channel in '|EN| ACTION/THRILLER' gains genre:Action + genre:Thriller).",
        "Covers ~15% of movies whose category segments match a known canonical genre; "
        "the other 85% are language/decade/platform groupings with no genre signal "
        "(correctly left untagged until TMDb integration).",
        "A strict allowlist prevents junk labels like 'NETFLIX MOVIES' or 'TOP IMDB' "
        "from leaking into the genre namespace.",
        "Genre tags derived from the provider category are confidence-labeled as "
        "CONF_STRONG_PRIOR (inferred from a grouping label, not a source-denoted genre "
        "field) — TMDb will supersede them at higher confidence when integrated.",
        "A one-time re-tagging migration runs at next launch to apply these genre tags "
        "to all existing movies and series.",
    ),
    test_steps=(
        "Open the Recipe chip (🧭 Discover) → add a Genre ingredient (e.g. Genre: Action) "
        "→ confirm the 'Now Plating' strip now includes MOVIES (not just series) tagged "
        "with Action from their provider category.",
        "Add a second genre ingredient (e.g. Genre: Thriller) alongside Action → confirm "
        "movies tagged with both Action AND Thriller appear.",
        "In Discover or Recipe results, find a movie from a language/platform category "
        "like '|EN| NETFLIX MOVIES' — confirm it has NO genre:Netflix or genre:Movies "
        "tag (the strict allowlist must have rejected those tokens).",
        "Restart the app after the first launch post-update → confirm the migration "
        "progress bar appears briefly ('Building content tags…') and completes without "
        "error before the main window is fully usable.",
        "Open a movie details pane for a title from an ACTION category → click the "
        "genre chip (Action) → confirm the channel list filters to Action movies.",
    ),
)
