from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=174,
    version="0.13.1",
    date="2026-07-31",
    title="Fix: deleting a source could crash the app",
    items=(
        "Fixed a crash ('database is locked') that could abort the app while "
        "deleting a source, now that the delete runs in the background — a database "
        "setting was being re-applied on every connection and collided with the "
        "in-progress delete. Deleting a source is now safe.",
        "macOS builds are Apple-Silicon (arm64) only from this release. Intel Macs "
        "top out at macOS Sequoia and demand is negligible; dropping the x86_64 build "
        "keeps releases simpler.",
    ),
    test_steps=(
        "Delete a large source while the app is running (background enrichment/loading "
        "active): the app must NOT crash or show 'database is locked' — the source is "
        "removed and the views refresh.",
        "Relaunch and confirm the app opens normally (database pragmas still apply).",
    ),
)
