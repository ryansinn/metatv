from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=571,
    version="0.88.0",
    date="2026-09-03",
    title="Trailer moves to its own row — Watch Later gets its width back",
    items=(
        "The Trailer button used to share a row with Watch Later, pinned to "
        "the left. At a narrow details pane there was no slack left for Watch "
        "Later to absorb, so it collapsed to a several-pixel sliver whenever a "
        "title had a trailer.",
        "Trailer now gets its own full-width row between Play/Resume and Watch "
        "Later. Watch Later is back to its full labeled size, and titles with "
        "no trailer (most of them) see no empty gap where the row would be.",
    ),
    test_steps=(
        "Open a title that has a trailer at a narrow details-pane width → "
        "Trailer sits on its own row under Play, and Watch Later is full-size "
        "again.",
        "Open a title without a trailer → no empty gap where the row would "
        "be.",
    ),
)
