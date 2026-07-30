from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=160,
    version="0.10.0",
    date="2026-07-30",
    title="Background clean-up now refreshes Discover, Recipes and filter counts too",
    items=(
        "When a background migration finishes reorganising your library — for "
        "example collapsing cross-language or cross-source duplicates onto one "
        "card — Discover, the Recipe shelves and the filter-panel counts now "
        "update straight away, alongside the main channel list.",
        "Previously only the main list refreshed, so those other views kept "
        "showing the pre-clean-up picture until you restarted the app.",
    ),
    test_steps=(
        "Start the app so a background migration that changes duplicate-grouping "
        "runs at launch (e.g. a content-identity backfill). Once the migration "
        "overlay finishes, open Discover WITHOUT restarting: the newly-collapsed "
        "variants show as single cards, not the old separate ones.",
        "Also without restarting, open a Recipe shelf and the filter panel: the "
        "shelf cards and the facet counts reflect the migration's new grouping "
        "(they no longer require an app restart to update).",
    ),
)
