from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=46,
    version="0.9.0",
    date="2026-06-23",
    title="Recipe Builder",
    items=(
        "New ✦ Recipe chip in the nav bar — build a faceted 'recipe' to find exactly what you want to watch.",
        "Left 'Pantry' sidebar lists all available facets (Genre, Language, Region, Platform, Decade, Quality, Collection) with distinct-value counts.",
        "Click any facet to open its weighted tag cloud — tags sized by how many channels carry them.",
        "Click a tag to include it (✓), click again to exclude it (⊘), click once more to remove it.",
        "Right 'Tonight's Recipe' rail groups your picks by role (BASE / IN / FROM / ON / ERA / FINISH / SET) with an auto-generated editorial name.",
        "'Now Plating' strip shows matching channels live as you build the recipe.",
    ),
    test_steps=(
        "Click the ✦ Recipe chip in the nav bar → Recipe view opens with an empty Pantry and empty recipe rail.",
        "Click a facet (e.g. Genre) in the Pantry → a weighted tag cloud expands with tag counts.",
        "Click a tag (e.g. 'Drama') → tag appears in the recipe rail marked ✓; 'Now Plating' strip updates.",
        "Click the included tag again → it toggles to ⊘ excluded; strip result count drops.",
        "Click the excluded tag again → it is removed from the recipe rail entirely.",
        "Build a multi-facet recipe (Genre + Language) → recipe rail groups by role with an auto-generated name.",
    ),
)
