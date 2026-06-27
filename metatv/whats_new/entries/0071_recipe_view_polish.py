from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=71,
    version="0.9.0",
    date="2026-06-27",
    title="Recipe view: Now-Plating context menu + Pantry filter clear",
    items=(
        "Right-clicking a card in the Now Plating section (or the Show All browse grid) "
        "now shows the standard channel context menu — play, favorite, queue, rate, "
        "monitor, hide, and more — via the unified channel menu registry.",
        "The Pantry facet sidebar now has a filter text box to quickly narrow the "
        "facet list (Genre, Language, Region, etc.) by name, with a × clear button.",
        "The Recipe 'Clear' button now also clears the Pantry filter text box, "
        "restoring the full facet list alongside resetting the recipe ingredients.",
    ),
    test_steps=(
        "Open the Recipe view (✦ chip). Add a tag to build a recipe — cards appear "
        "in 'Now Plating'. Right-click a card: the standard channel context menu "
        "should appear with Play, Favorite, Queue, and other standard actions.",
        "Click 'Show all →' to open the full-results browse grid. Right-click a card "
        "there: the same context menu should appear.",
        "In the Pantry sidebar, type 'lang' in the filter box — only 'Language' (and "
        "any other facet whose name contains 'lang') should remain visible. "
        "Click the × button: all facets should reappear.",
        "With the Pantry filter text containing some text, click the 'Clear' button "
        "in the Recipe rail (bottom-right). The filter text box should clear and all "
        "Pantry facet rows should become visible again.",
    ),
)
