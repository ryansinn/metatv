from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=240,
    version="0.21.0",
    date="2026-08-02",
    title="Optional: collapse quality/language versions in the channel list",
    items=(
        "A library with the same movie or show available in several qualities "
        "or languages used to show every copy as its own row. There's now an "
        "opt-in Settings → Interface → Channel List checkbox, 'Collapse "
        "quality/language versions into one row', that shows just the best "
        "copy with a '×N' badge — right-click it and choose 'Show N versions' "
        "to pick a specific quality/language/source. Off by default; a "
        "hidden/expired source's copy is never picked as the shown one when a "
        "visible copy exists, and movies/series with the same title never "
        "merge.",
    ),
    test_steps=(
        (
            "Open Settings → Interface → Channel List and turn on 'Collapse "
            "quality/language versions into one row', then OK.",
            "settings:Interface",
        ),
        "Find a title that has multiple quality/language copies in your "
        "library → it now shows as one row with a '×N' badge next to the "
        "other badges.",
        "Right-click that row → 'Show N versions' appears; choosing an entry "
        "plays that specific copy.",
        "Turn the setting back off and reopen the channel list → every "
        "variant row reappears individually.",
    ),
)
