from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=621,
    version="0.103.0",
    date="2026-09-07",
    title="Icon buttons render crisply, follow the theme, and say what they do",
    items=(
        "Icon-only buttons across the app — the Discover shelf pin/hide/"
        "collapse controls, the trail map's watched badge and favourite star, "
        "the filter and category dialogs, the preferences dashboard, the "
        "watchlist and source rows — now draw a real vector icon instead of a "
        "colour emoji squeezed into the button as text, so they are no longer "
        "clipped at their fixed sizes.",
        "Those icons repaint when you switch themes, instead of keeping the "
        "previous palette's colour until the next restart.",
        "The Discover shelf's pin and collapse buttons and the trail map's "
        "watched badge and favourite star now have tooltips; they had none.",
        "There is one close glyph in the app again — the context-filter "
        "dismiss button used a second, different '✕' from every other close.",
    ),
    test_steps=(
        "Discover → hover a shelf header → the pin and collapse buttons show "
        "tooltips (\"Pin to top\" / \"Collapse\"), and their icons are sharp "
        "rather than clipped emoji.",
        "Settings → Appearance → switch the theme → every icon button "
        "(shelf pin/collapse, dialog close ×, watchlist remove) recolours "
        "immediately, with no restart.",
        "Browse → click a genre in the details pane to raise a context filter "
        "chip → its dismiss button shows the same × as the watchlist and "
        "filter-chip closes.",
        "Explore → open a trail-map card → hover the poster's watched badge "
        "and the title's star → both name what clicking them will do, and the "
        "star fills when toggled.",
    ),
)
