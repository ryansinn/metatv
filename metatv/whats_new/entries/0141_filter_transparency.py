from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=141,
    version="0.9.0",
    date="2026-07-21",
    title="Search now shows what each filter layer is hiding — per layer",
    items=(
        "When a search (including the search opened by clicking a \"Watching for\" "
        "alert) hides results, a gold bar now breaks the hidden count down by layer: "
        "\"🔒 N hidden by Global Exclusions\" and \"🔎 N hidden by search filters\" — "
        "so content is never dropped silently.",
        "Click a segment to reveal just that layer for the current view only. Your "
        "Global Exclusions and filter settings are never changed — the next search or "
        "filter change restores the normal filtered view.",
        "This fixes the case where an alert's results (e.g. English titles) seemed to "
        "vanish because their region was globally excluded: now you can see exactly "
        "how many were held back and reveal them in one click.",
    ),
    test_steps=(
        "With a Global Exclusion active (exclude a region/category that a search would "
        "otherwise match), run a search whose matches include excluded content: a gold "
        "\"🔒 N hidden by Global Exclusions — show\" segment appears above the list.",
        "Click the 🔒 segment: the previously-hidden results appear in this view and a "
        "banner notes exclusions are suspended; open Settings and confirm your Global "
        "Exclusions are unchanged.",
        "With a Tier-1 filter active (e.g. a Platform facet) plus a search, confirm a "
        "\"🔎 N hidden by search filters — show\" segment appears and clicking it reveals "
        "the tag-filtered matches; both segments can show at once when both layers hide.",
        "Edit the search text or change a filter: both reveals reset and the bar "
        "recomputes for the new query.",
    ),
)
