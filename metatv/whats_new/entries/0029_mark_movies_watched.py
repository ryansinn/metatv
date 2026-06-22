from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=29,
    version="0.7.6",
    date="2026-06-22",
    title="Mark movies & series watched from the list",
    items=(
        "Right-click any movie or series in the channel list and choose "
        "'Mark as Watched' or 'Mark as Unwatched' to set its watch state "
        "without playing it. The ✓ indicator updates immediately.",
        "Manually marked items always render with a solid ✓ (not the muted "
        "gray used for queue-auto-advanced items), so you can tell at a glance "
        "which items you deliberately finished vs. items that auto-played.",
        "Episode toggle (Mark Season / Mark as Watched in the series tree) also "
        "now correctly records a solid indicator — the in-place icon now agrees "
        "with a full reload every time.",
        "Watch indicator icons are now crisp on Retina / HiDPI displays, and "
        "use the correct FONT_LG size token (12 px) instead of a hardcoded value.",
    ),
)
