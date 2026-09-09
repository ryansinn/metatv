from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=652,
    version="0.112.0",
    date="2026-09-08",
    title="Deleting a channel or a source no longer mishandles its series rows",
    items=(
        "Deleting a channel (a source that stopped listing it, or the source's own "
        "removal) tries to take that channel's season/episode rows with it, but the "
        "check compared the wrong id — the app's own internal channel id — against a "
        "column that stores the provider's own series id, the same mismatch #822 just "
        "fixed for series monitoring. The check could never match, so a deleted "
        "channel's seasons and episodes were quietly left behind instead of removed.",
        "Removing an entire source had the same mismatch in its \"is this series still "
        "kept?\" check, and there it was the more serious direction: a favorited "
        "series that survives a source removal could have its seasons and episodes "
        "stripped anyway, because the check meant to recognize it as kept could never "
        "match. Both are fixed by matching on the provider's series id paired with "
        "its provider — never the id alone, which can collide across two different "
        "sources and would otherwise let one source's delete reach into another's "
        "rows.",
    ),
    test_steps=(
        "Favorite a series with downloaded season/episode data, then delete its "
        "source from Manage Sources — the series still appears in Favorites with its "
        "seasons and episodes intact.",
        "Let a non-favorited channel drop out of a source's catalog on refresh (or "
        "delete a non-favorited series' source outright) — its season/episode rows "
        "no longer linger in the database afterward.",
    ),
)
