from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=681,
    version="0.128.0",
    date="2026-10-01",
    title="A Linux download: MetaTV.flatpak",
    items=(
        "The rolling release now carries MetaTV.flatpak beside the macOS .dmg. "
        "It bundles its own mpv and shares the same library, settings and "
        "history as running from source (~/.config/metatv and friends) — so "
        "don't run both at once. Downloads and recordings still go to "
        "~/Videos/MetaTV.",
    ),
    test_steps=(
        "Download MetaTV.flatpak from the rolling release and run "
        "'flatpak install --user MetaTV.flatpak', then launch MetaTV from the app "
        "menu — it opens with your existing sources and history.",
        "Play a channel and an episode — the mpv window opens with its on-screen "
        "controls and plays.",
        "Settings → Check for updates now — a notice says this is the Flatpak build "
        "and to install the newest MetaTV.flatpak, instead of offering a .dmg.",
    ),
)
