from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=119,
    version="0.9.0",
    date="2026-06-28",
    title="Region chips now appear for category-tagged content",
    items=(
        "A huge amount of VOD whose provider category is a bracketed locale code "
        "(e.g. \"|FR|\") used to show \"REGION: FR\" deep in the Tags section but "
        "had NO matching [FR] chip on the left of its list/search rows. Region is "
        "now filled from the provider category at ingestion, so those rows get the "
        "left [FR] chip automatically.",
        "When neither the name nor the provider category carries a region, a row "
        "can also inherit one from a sibling that shares its content identity "
        "(the same title across your other sources) — so a region you have on one "
        "source propagates to the matching item on another.",
        "These fills are additive only: a region already detected from the channel "
        "name is never overwritten, and a row keeps its own category's code rather "
        "than borrowing a different one from a sibling.",
    ),
    test_steps=(
        "Find a VOD whose provider category is a bracketed locale code such as "
        "\"|FR|\" (its details Tags show \"REGION: FR\"). In the channel/search "
        "list its row now shows a left [FR] chip next to the title.",
        "Open a title whose NAME already implies a region (e.g. a \"(US)\" suffix). "
        "Confirm its left chip still reflects the NAME's region — it is not "
        "replaced by the provider category's code.",
    ),
)
