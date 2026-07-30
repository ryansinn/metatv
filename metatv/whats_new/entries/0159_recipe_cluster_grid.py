from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=159,
    version="0.10.0",
    date="2026-07-30",
    title="Recipe builder opens on a facet overview — every facet's tags at a glance",
    items=(
        "The Recipe builder (✦ chip) now opens on a \"cluster grid\": a compact "
        "tag-cloud for every browse facet — Genre, Region, Language, Collection and "
        "Decade — shown side by side, so you can build a filter across facets "
        "without clicking through them one at a time.",
        "Click any tag to add it to your recipe and stay on the overview; click a "
        "facet's heading to drill into its full cloud, and \"‹ All facets\" to come "
        "back.",
        "The Decade tile is laid out in chronological order (oldest → newest) "
        "instead of by popularity, so eras read left-to-right the way you expect.",
        "Lower-volume facets (Quality, Platform, Audio Format, Subtitles) tuck into "
        "a collapsible \"More facets\" section, and the Tonight's Recipe panel has a "
        "collapse chevron so the grid can stretch nearly full-width — both remember "
        "their state.",
        "The old single-facet Pantry list is gone; a search box above the grid still "
        "finds tag values across every facet at once.",
    ),
    test_steps=(
        "Open the ✦ Recipe chip: the center shows a grid of mini tag-clouds — one "
        "per facet (Genre, Region, Language, Collection, Decade) — not a single "
        "facet list.",
        "Click a tag inside the Genre tile, then one inside the Region tile: both "
        "land in Tonight's Recipe and the view stays on the grid (cross-facet build "
        "without leaving the overview).",
        "Click the \"Genre\" heading of its tile → it drills into Genre's full "
        "cloud; click \"‹ All facets\" → you return to the grid with your "
        "ingredients intact.",
        "Confirm the Decade tile reads oldest → newest (e.g. 1980s before 2020s), "
        "not by count.",
        "Expand \"▸ More facets\", collapse the Tonight's Recipe panel with its "
        "chevron, switch away and back to the Recipe chip → both remember their "
        "collapsed/expanded state.",
        "Type in the search box above the grid (e.g. \"comedy\") → matches from "
        "several facets appear color-coded; clear it → the cluster grid returns.",
    ),
)
