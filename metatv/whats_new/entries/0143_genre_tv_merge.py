from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=143,
    version="0.9.0",
    date="2026-07-21",
    title="Merged the fragmented 'TV program / series / show' genres into one 'TV Show'",
    items=(
        "The GENRE filter used to list a dozen near-duplicate entries — "
        "'TV program', 'TV programme', 'TV Series', 'Television series', "
        "'Program Tv', even provider typos like 'TV proramme' — because TMDB "
        "has no single 'TV' genre and providers each label it differently. "
        "These now fold into ONE canonical 'TV Show' entry with the combined "
        "count, so the panel is far less cluttered.",
        "Distinct genres are untouched: Talk Show, Game Show, Reality Show, "
        "Music Show, TV Movie, and Drama series each stay their own entry, and "
        "the ambiguous bare 'Show' is left alone.",
        "A one-time background pass re-tags your existing channels so the merge "
        "takes effect without a manual full refresh. Your favorites, ratings, "
        "queue, history, and hand-added tags are untouched.",
    ),
    test_steps=(
        "Open the filter panel and expand the GENRE section → there is a single "
        "'TV Show' entry, NOT separate 'TV program' / 'TV programme' / "
        "'TV Series' / 'Television series' rows.",
        "Note the count on 'TV Show' → it is the SUM of the previously "
        "fragmented labels (roughly the old TV program + programme + Series + "
        "Television series + Program Tv totals combined).",
        "Select the 'TV Show' genre → the channel list populates with the "
        "matching channels (those that carried any of the old TV-program/series "
        "labels).",
        "Confirm 'Talk Show', 'Game Show', 'Reality Show', and 'TV Movie' still "
        "appear as their own separate GENRE entries (they must NOT be folded "
        "into 'TV Show').",
    ),
)
