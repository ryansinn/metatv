from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=56,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe browse collapses variants into one card per title",
    items=(
        "Recipe 'Now Plating' and 'Show all' now show ONE card per production "
        "(same title + type + year), collapsing duplicates from different sources "
        "or quality tiers into a single representative card.",
        "Collapsed cards display a ×N badge (e.g. ×3) when multiple "
        "source/quality variants exist — hover for a tooltip with the count.",
        "The YIELDS count matches the number of distinct collapsed cards, not "
        "raw channel rows.",
        "The highest-quality variant (4K > FHD > HD > SD) is chosen as the "
        "representative; ties broken by channel id.",
        "The details pane 'Categories' section still lists all individual "
        "variants — collapse is browse-only.",
    ),
    test_steps=(
        "Open the Recipe chip (✦) → add a broad tag (e.g. Genre: Drama) → "
        "'Now Plating' populates. Confirm no duplicate titles appear for "
        "channels that exist in multiple sources.",
        "Find a card with a ×N badge (e.g. ×3). Hover over it — tooltip says "
        "'3 source / quality variants of this title available'.",
        "Click 'Show all →'. Confirm the YIELDS count in the recipe rail matches "
        "the number of distinct cards in the full browse grid (not the raw channel count).",
        "In 'Show all', type a title in the Filter box. Confirm results narrow "
        "and still show deduplicated cards (no duplicates visible).",
        "Scroll to the bottom of 'Show all' to trigger lazy loading. Confirm "
        "additional pages load and continue to show one card per title.",
        "Click a collapsed card to open the details pane. Confirm 'Categories' "
        "still lists all the individual provider variants.",
        "Switch to list view (☰ List) in 'Show all'. Confirm collapsed cards "
        "show ·×N in the list row text where variants exist.",
    ),
)
