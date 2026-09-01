from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=492,
    version="0.64.0",
    date="2026-09-01",
    title="Sports kept showing yesterday's fixtures",
    items=(
        "After refreshing a source, the Sports and Events views carried on "
        "showing the old fixture names until you switched away and back.",
        "Sports channels are reused: the same slot carries a different game "
        "each day and your source renames it. So the list could offer you one "
        "game while the channel behind it was already showing another — the "
        "data was right, the list simply had not caught up.",
        "Every other view already re-read itself after a source refresh. "
        "Sports and Events now do too.",
    ),
    test_steps=(
        ("Open Sports, refresh a source, and confirm the fixture names update "
         "without switching views.", "view:sports"),
        ("Do the same on Events.", "view:events"),
        "Refresh with Sports hidden, then open it, and confirm it shows "
        "current fixtures.",
    ),
)
