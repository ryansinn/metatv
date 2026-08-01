from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=188,
    version="0.14.2",
    date="2026-07-31",
    title="Details pane: genres like 'Action & Adventure' show a real '&' and wrap cleanly",
    items=(
        "Genre chips (and the other facet/category/version chips) now display a "
        "literal ampersand. Before, a lone '&' was swallowed as a keyboard "
        "accelerator, so 'Action & Adventure' rendered as 'Action _Adventure' "
        "(a stray underscore) and 'Sci-Fi & Fantasy' as 'Sci-Fi _Fantasy'.",
        "Filtering is unchanged — clicking a genre still filters by the real "
        "'Action & Adventure'; only the on-screen label is corrected.",
        "The genre chips wrap onto additional rows at the pane width and never "
        "truncate, even when another section (like a long version-source label) "
        "tries to widen the column.",
    ),
    test_steps=(
        "Select a title whose genres include 'Action & Adventure' or 'Sci-Fi & "
        "Fantasy' (e.g. a TMDB-tagged movie/series) → each genre chip shows a real "
        "'&' with no stray underscore.",
        "Click the 'Action & Adventure' chip → the channel list filters to that "
        "genre (the click uses the real value, not the escaped display text).",
        "Narrow the details pane → the genre chips wrap onto more rows and stay "
        "within the pane; no chip's text is cut off.",
    ),
)
