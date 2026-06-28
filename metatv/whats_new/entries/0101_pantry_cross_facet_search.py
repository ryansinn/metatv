from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=101,
    version="0.9.0",
    date="2026-06-28",
    title="Recipe Pantry search now finds tags across ALL facets",
    items=(
        "The Recipe Builder's Pantry search box now searches actual tag VALUES "
        "across every facet at once — type 'comedy' and the center cloud fills with "
        "matching tags from Genre, Collection, Category, and more, color-coded by "
        "facet, sized by popularity.",
        "Each left-hand facet row shows a subtle '·N' badge telling you how many "
        "matching tag values live in that facet, so you can see where your search "
        "landed at a glance.",
        "Clicking a matched tag adds it to the recipe under its correct facet — even "
        "when it's a different facet than the one currently selected.",
        "Clearing the search box returns the cloud to the selected facet's tags "
        "(the original behavior). The old facet-row name filter is replaced by this "
        "more useful value search.",
    ),
    test_steps=(
        "Open the Recipe Builder (✦ chip) and type 'comedy' in the Pantry search box; "
        "confirm the center cloud fills with matching tags drawn from MULTIPLE facets "
        "(e.g. Genre and Collection), color-coded by facet and sized by popularity, "
        "with the header reading 'Matches for \"comedy\"'.",
        "Confirm each left facet row shows a '·N' badge equal to how many tag values "
        "matched in that facet (facets with no matches show no badge).",
        "Click a matched tag that belongs to a facet OTHER than the one selected; "
        "confirm it is added to the recipe rail under its OWN facet (correct role "
        "group) and the tag shows its include mark.",
        "Clear the search box (× or delete the text) and confirm the badges disappear "
        "and the cloud returns to the selected facet's tag list.",
    ),
)
