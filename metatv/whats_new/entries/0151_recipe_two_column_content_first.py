from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=151,
    version="0.10.0",
    date="2026-07-22",
    title="Recipe view: two-column layout + content-first tag entry",
    items=(
        "The Recipe view dropped from three columns to two. Column 1 now stacks "
        "The Pantry over Tonight's Recipe (the ingredient card moved under the "
        "pantry, filling the space it used to leave empty). Column 2 is the "
        "weighted tag cloud over a real, half-height \"Now Plating\" results grid "
        "— the matches area is no longer a thin clipped strip.",
        "Right-clicking a tag in the details pane now opens the Recipe view "
        "content-first: you land straight on the full-results grid showing what "
        "matches that tag, with the tag already applied as the recipe ingredient "
        "— not on the builder. A \"Build recipe\" link on that page takes you into "
        "the builder (with the ingredient already in place) whenever you want to "
        "refine it. Opening the Recipe view from the bottom-nav chip still lands "
        "on the builder as before.",
        "Every divider in the new layout is a draggable splitter — pantry vs "
        "recipe rail, the two columns, and the cloud vs results — and each "
        "remembers where you left it across restarts.",
    ),
    test_steps=(
        "In the details pane, right-click a tag chip (e.g. a Genre): the Recipe "
        "view opens showing the grid of matching content, with that tag applied "
        "as the recipe ingredient — NOT the empty builder.",
        "On that results page, click \"Build recipe\": you land on the builder "
        "with the same tag already in Tonight's Recipe.",
        "Open the Recipe view from the bottom-nav Recipe chip: it opens on the "
        "builder (two columns — Tonight's Recipe sits under The Pantry in column "
        "1; the tag cloud sits over a half-height Now Plating grid in column 2).",
        "Drag the divider between the tag cloud and the Now Plating grid, restart "
        "the app, and reopen the Recipe view: the split is where you left it.",
    ),
)
