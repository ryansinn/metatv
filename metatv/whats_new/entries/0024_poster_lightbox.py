from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=24,
    version="0.7.5",
    date="2026-06-22",
    title="Click-to-enlarge poster lightbox",
    items=(
        "Click the poster image in the details pane to open a full-res view "
        "in a centred lightbox overlay. The image scales to fit the window "
        "while preserving aspect ratio.",
        "Dismiss by pressing Esc or clicking anywhere outside the image.",
        "The pointer cursor and tooltip ('Click to enlarge') appear "
        "automatically once the poster is loaded.",
    ),
)
