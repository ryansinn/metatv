from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=26,
    version="0.7.6",
    date="2026-06-22",
    title="Dim fully-watched titles in the channel list",
    items=(
        "Movies and series you have finished now render in a subtly muted foreground "
        "color in the channel list, so completed titles recede and unwatched or "
        "in-progress content stands out at a glance.",
        "Live channels are not affected — the dimming only applies to VOD content "
        "(movies, series, episodes) that carries a completed-watch flag.",
    ),
)
