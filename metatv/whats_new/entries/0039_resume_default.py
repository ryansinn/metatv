from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=39,
    version="0.9.0",
    date="2026-06-22",
    title="Playback resume default + per-play override actions",
    items=(
        "Settings → Playback now has a 'When starting playback' option: 'Resume where left off' (default) or 'Start from beginning'.",
        "Right-click any in-progress movie for a one-time override: 'Play from Beginning' ignores the saved position; 'Resume from M:SS' forces a resume even when the default is 'Start from beginning'.",
        "The one-time overrides never change your saved resume position — they apply only to the current play.",
    ),
)
