from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=22,
    version="0.7.3",
    date="2026-06-22",
    title="Graduated watch-progress indicators (◔ ◐ ◕)",
    items=(
        "Watch progress is now shown with four graduated glyphs instead of a single ◐: "
        "◔ (~quarter watched), ◐ (~half), ◕ (~three-quarter), and ✓ (completed). "
        "Both the channel list and the series episode tree use the same indicators.",
        "A new 'Mark as partially-watched after' threshold in Settings → Playback controls "
        "the minimum percentage before any progress glyph appears (default 10%). "
        "Items watched below this percentage are treated as untouched.",
        "Watch percentage is now stored in the database so the correct glyph renders "
        "instantly from the stored value — no per-row duration lookups at display time.",
    ),
)
