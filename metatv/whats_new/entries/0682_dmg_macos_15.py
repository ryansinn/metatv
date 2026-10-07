from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=682,
    version="0.129.0",
    date="2026-10-06",
    title="The Mac download is current again — now needs macOS 15",
    items=(
        "No new MetaTV.dmg had been built since 13 September: the build machine "
        "could no longer install mpv. It now builds on macOS 15, so the Mac "
        "download tracks the latest code again — and needs macOS 15 (Sequoia) "
        "or later on Apple Silicon.",
    ),
    test_steps=(
        "Download MetaTV-arm64.dmg from the rolling release on a macOS 15 Mac — "
        "the title bar's build id shows today's date, not 2026-09-13.",
        "Open MetaTV and play a channel — the bundled mpv opens and plays.",
    ),
)
