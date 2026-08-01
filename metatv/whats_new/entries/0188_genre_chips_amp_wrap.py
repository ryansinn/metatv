from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=188,
    version="0.15.0",
    date="2026-07-31",
    title="Details pane: genres like 'Action & Adventure' show a real '&' and wrap cleanly",
    items=(
        "Genre chips (and the other facet/category/version chips) now display a "
        "literal ampersand. Before, a lone '&' was swallowed as a keyboard "
        "accelerator, so 'Action & Adventure' rendered as 'Action _Adventure' "
        "(a stray underscore) and 'Sci-Fi & Fantasy' as 'Sci-Fi _Fantasy'.",
        "Filtering is unchanged — clicking a genre still filters by the real "
        "'Action & Adventure'; only the on-screen label is corrected.",
        "The Tags panel's facet rows (GENRE, LANGUAGE, REGION, DECADE, COLLECTION) "
        "now WRAP onto additional lines at the panel width instead of crushing every "
        "chip onto one row (which cut the text down to fragments like 'tion & Adver' "
        "or 'Animatio'). The details header genres wrap the same way.",
    ),
    test_steps=(
        "Select a title whose genres include 'Action & Adventure' or 'Sci-Fi & "
        "Fantasy' (e.g. a TMDB-tagged movie/series) → in both the header and the "
        "'\U0001f3f7 Tags' panel GENRE row, each chip shows a real '&' with no stray "
        "underscore.",
        "With several genres shown, look at the Tags panel GENRE row → the chips wrap "
        "onto multiple rows; none is squished/truncated ('tion & Adver' / 'Animatio').",
        "Click the 'Action & Adventure' chip → the channel list filters to that genre "
        "(the click uses the real value, not the escaped display text).",
    ),
)
