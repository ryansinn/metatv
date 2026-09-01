from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=502,
    version="0.64.0",
    date="2026-09-01",
    title="Clicking through Settings rewrote your whole config each time",
    items=(
        "Every time you selected a different section in Settings, MetaTV wrote "
        "your entire configuration file to disk — and copied the old one to a "
        "backup first. Walking down the list wrote it eight times over.",
        "It now remembers which section you were on and writes once, when you "
        "close the dialog. Which section you last used is still remembered.",
    ),
    test_steps=(
        "Open Settings, click through every section, then close it — and "
        "confirm the section you were last on is still selected when you "
        "reopen it.",
        "Change a setting, click OK, and confirm it took effect.",
        "Open Settings and press Cancel; confirm nothing you touched was kept.",
    ),
)
