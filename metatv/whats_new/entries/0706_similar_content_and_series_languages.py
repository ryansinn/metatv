from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=706,
    version="0.146.0",
    date="2026-10-09",
    title="Similar Content works without TMDb; series show their episodes' languages",
    items=(
        "Similar → Content now always shows something: TMDb's recommendations when a "
        "TMDb key is set, otherwise titles matched by this one's genres, director and "
        "cast (respecting your exclusions).",
        "Languages heard in a played or probed episode are added to the series copy "
        "that holds that episode — never to its other variants.",
    ),
    test_steps=(
        "With no TMDb key, select a film with genres/cast and switch Similar to "
        "Content — a list of related titles appears.",
        "Play an episode of a series for a few seconds, reselect the series — its "
        "Details Language row includes the heard language ('· seen in the file'); "
        "another copy of the same series does not gain it.",
    ),
)
