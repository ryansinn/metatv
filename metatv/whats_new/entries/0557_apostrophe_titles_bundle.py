from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=557,
    version="0.86.0",
    date="2026-09-03",
    title="Titles with apostrophes now bundle correctly",
    items=(
        "Titles that differ only in apostrophe — like \"Three's Company\" and "
        "\"Threes Company\" — are now recognized as the same production and "
        "bundle into a single card (measured: 1,328 title buckets were split "
        "only this way in the owner's library — Clarkson's Farm, Grey's Anatomy, "
        "The Queen's Gambit, …).",
    ),
    test_steps=(
        "Search for a title you know appears in multiple sources with apostrophe "
        "variations (e.g. \"Three's Company\") → one bundled card is shown, with "
        "all language/quality variants under \"Other Versions\".",
        "First launch after update shows the content-identity rebuild task; when "
        "it finishes, Recommended and Favorites no longer show apostrophe variants "
        "as separate cards.",
    ),
)
