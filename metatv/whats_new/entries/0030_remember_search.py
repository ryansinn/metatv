from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=30,
    version="0.7.6",
    date="2026-06-22",
    title="Remember Last Search",
    items=(
        "New setting: 'Remember last search' (Settings → Search, on by default). "
        "When enabled, MetaTV saves your search query, source filter, All/Hidden toggle, "
        "and any active genre or cast/crew chip each time they change, then restores "
        "them automatically the next time you launch the app.",
        "The saved state is restored before the initial channel load, so the results "
        "panel comes up showing exactly what you were looking at last session — no "
        "manual re-entry needed.",
        "Turn the setting off in Settings → Search to always start with a blank search "
        "on launch.",
    ),
)
