from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=85,
    version="0.9.0",
    date="2026-06-28",
    title="Recipe / Show-all results now appear in under a second",
    items=(
        "Recipe results and the Show-all search/filter now appear in well under a "
        "second instead of 5–10 s on large libraries. The faceted query was rewritten "
        "to anchor its driving scan on the first ingredient's tag membership rather "
        "than enumerating the entire 1.2M-row content_tags table, cutting a "
        "single-facet count + sample from ~15 s combined to under 1 s.",
        "Switching between ingredients (adding, removing, or changing a facet) is "
        "now near-instant — each change re-issues a fast anchored query instead of a "
        "full-table scan.",
        "A new composite index (tag_id, channel_id) on content_tags further speeds "
        "the per-facet GROUP BY queries that drive the tag cloud and pantry counts.",
    ),
    test_steps=(
        "Open the Recipe view (✦ chip), select a broad facet like Genre in the "
        "Pantry sidebar, and click a high-count tag such as Drama. The 'Now Plating' "
        "results and the YIELDS count should appear in under ~1 second (previously "
        "5–10 s on a large library).",
        "Add a second ingredient from another facet (e.g. select Language and click "
        "English). Results should refresh near-instantly and show only channels "
        "matching BOTH ingredients (the AND intersection).",
        "Remove the Language ingredient and add a different Genre value (e.g. "
        "Action). The result set should update quickly, showing only channels "
        "matching the new single-facet recipe.",
        "Click 'Show all →', then type a keyword in the filter/search box. The "
        "filtered results should update quickly and lazy-load more cards as you "
        "scroll down the grid.",
        "Click the Clear button to reset the recipe. Open the Pantry again and "
        "pick a niche facet with a low count (e.g. a specific platform). Results "
        "should still appear in well under a second.",
    ),
)
