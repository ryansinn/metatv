from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=262,
    version="0.24.0",
    date="2026-08-02",
    title="Packaged app now shows version in title bar",
    items=(
        "The window title now displays the release version (e.g. 'MetaTV 0.24.0') "
        "when running the packaged app, where git information is unavailable.",
        "Previously, packaged builds showed just 'MetaTV' in the title bar, "
        "while source checkouts showed rich identity like 'MetaTV (release/0.24.0 a914212)'. "
        "Now both paths provide clear version information.",
        "The git-rich title format (with branch/commit/PR info) is unchanged for "
        "source checkouts — this is a development-focused improvement for packaged builds only.",
    ),
    test_steps=(
        "In a source checkout, verify the window title still shows the rich format "
        "with branch name and commit hash (e.g. 'MetaTV (main a914212)').",
        "In a packaged DMG build, verify the window title now shows the version "
        "(e.g. 'MetaTV 0.24.0') instead of bare 'MetaTV'.",
    ),
)
