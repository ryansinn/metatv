from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=107,
    version="0.9.0",
    date="2026-06-28",
    title="Clickable Tags & Collections in the details pane",
    items=(
        "The Tags chips in the details pane are now interactive. LEFT-CLICK a tag "
        "to filter the channel list down to that exact tag — the same strict "
        "context-filter chip used by genre/cast clicks (dismiss with its ✕).",
        "RIGHT-CLICK a tag to open the Recipe view seeded with just that one "
        "ingredient — its matching titles fill the 'Now Plating' poster shelf so "
        "you can browse everything carrying that tag.",
        "Collection chips are special: clicking one shows the actual human-curated "
        "provider set (the channel's category), not a re-guessed query on the noisy "
        "collection label — so you get the real grouping the provider shipped.",
        "Tag chips show a pointing-hand cursor and a tooltip spelling out the "
        "left-click / right-click actions.",
    ),
    test_steps=(
        "Open a movie or series with tags, LEFT-CLICK a Genre/Language/Region tag "
        "chip, and confirm the channel list filters to that exact tag with a "
        "'<Facet>: <value>' chip in the search bar; click the chip's ✕ to clear it.",
        "RIGHT-CLICK the same tag chip and confirm the Recipe view opens seeded with "
        "that one ingredient and the 'Now Plating' shelf fills with matching posters.",
        "Open a channel that has a Collection tag, LEFT-CLICK it, and confirm the "
        "list shows that channel's curated provider category set (a 'Collection: …' "
        "chip), not an empty/odd result from the raw collection label.",
        "Hover a tag chip and confirm the cursor is a pointing hand and the tooltip "
        "names the click (filter) and right-click (Discover) actions.",
    ),
)
