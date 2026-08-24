from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=342,
    version="0.41.0",
    date="2026-08-24",
    title="The details pane: a title with room, and 65 versions in one glance",
    items=(
        "The title has its row to itself. It used to share it with the region "
        "chip, the quality chip and the year — and since the title is the only "
        "one of those that can shrink, it wrapped around whatever they left. "
        "\"Monty Python's The Meaning of Life\" now takes two lines instead of four.",
        "Under it, a byline: \"Movie · 2024\". The region and quality badges "
        "moved one row down, beside the source, where nothing is competing "
        "with a wrapping title.",
        "\"Also available\" is grouped by region. Kraven The Hunter has 65 "
        "versions; it now reads DE 9 · EN 6 · NL 6 · PL 6 … with a \"+ 7 more\" "
        "tail, and the heading says \"65 versions · 19 regions\". Click a region "
        "to see its versions, ‹ All regions to come back.",
        "Every version is still there and still right-clickable — nothing is "
        "summarised away, and a region with no code of its own gets a bucket "
        "rather than falling out of the count.",
        "The poster art is centred on its card, so the action rail sits beside "
        "it rather than on top of it, and the Watched tick moved to the "
        "poster's top-right corner — clear of the title artwork it was landing on.",
    ),
    test_steps=(
        "Select a movie with a long title (e.g. \"Monty Python's The Meaning of "
        "Life\") → the title uses the full width of the pane and the region / "
        "quality chips are on the row below it, not beside it.",
        "Check the line under the title reads \"Movie · 2024\" (or \"Series · …\"), "
        "and a title with no year shows just the kind with no trailing dot.",
        "Select a widely-duplicated title (Kraven The Hunter, Don't Look Up) → "
        "\"Also available\" shows region chips with counts, at most 12, and the "
        "heading on the right reads \"N versions · M regions\".",
        "Click \"+ N more\" → the remaining regions appear and the tail goes.",
        "Click a region chip → it is replaced by that region's individual "
        "versions plus a \"‹ All regions\" link. Right-click one of them → the "
        "full version context menu still works (play / favourite / queue / hide).",
        "Click \"‹ All regions\" → back to the capped region grid.",
        "While drilled into a region, click a different channel in the list → "
        "the pane shows the new title's regions, not an empty grid.",
        "Select a movie with a poster → the art is centred on its card with the "
        "action rail to its left, and marking it watched puts the tick on the "
        "poster's top-right corner.",
        "Narrow the details pane to its minimum → the region chips and the "
        "badge row wrap; nothing is cut off at the right edge.",
    ),
)
