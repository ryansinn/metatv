from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=135,
    version="0.9.0",
    date="2026-07-15",
    title="Details action rail sits beside the poster",
    items=(
        "The slim action rail (favorite, monitor, hide, like/dislike) now sits in a "
        "gutter to the LEFT of the poster instead of floating over the poster art — "
        "the poster image shifts right by the rail's width so nothing is covered.",
        "The rail is a softer dark gray now, not near-black, and its buttons are "
        "horizontally centered.",
    ),
    test_steps=(
        "Open a movie's details: the action rail is a dark-gray column to the LEFT of "
        "the poster, not overlapping the artwork, and its icons are centered in the rail.",
        "Resize the details pane narrower and wider: the poster still fits within its "
        "area (no clipping off the right edge) and the rail stays put in the left gutter.",
    ),
)
