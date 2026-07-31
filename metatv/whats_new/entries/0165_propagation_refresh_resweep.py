from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=165,
    version="0.11.0",
    date="2026-07-30",
    title="Cross-source copies keep collapsing after every refresh",
    items=(
        "When you refresh your sources, MetaTV now re-checks the whole library "
        "for copies of the same title that can share an id. If one source now "
        "carries the TMDb id for a show and another source only has an idless "
        "copy, the idless copy adopts that id and the two fold onto a single "
        "card — no restart, no waiting for a background lookup.",
        "This closes a gap where a title stayed split forever: if the id-bearing "
        "copy arrived in a later refresh (after the one-time link pass had "
        "already run), the older idless copies were never revisited. They are now.",
        "It only ever merges same-type content — a movie and a series with the "
        "same name stay separate cards, as do genuine remakes with different ids. "
        "The pass is free (no network) and touches only generated data; your "
        "favourites, ratings and tags are never affected.",
    ),
    test_steps=(
        "With one source that carries a TMDb id for a series (e.g. '12 Monkeys') "
        "and another source that has an idless copy of the SAME series, run "
        "Refresh All; when the queue finishes, confirm the idless copies fold onto "
        "the id-bearing card (one card with a '×N' badge) — no restart needed.",
        "Confirm a MOVIE that shares a title with a series (same name, different "
        "type) does NOT merge into the series card — it stays its own separate card.",
        "Refresh again with nothing new to link and confirm the app stays "
        "responsive and the view does not needlessly reload (the re-sweep is a "
        "cheap no-op when nothing folds).",
    ),
)
