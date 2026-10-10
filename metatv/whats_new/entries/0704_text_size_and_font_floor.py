from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=704,
    version="0.144.0",
    date="2026-10-09",
    title="One text size everywhere, and a Text size setting",
    items=(
        "Text that had no style of its own (series tree rows, menus, dialogs, plain "
        "labels) followed the operating system's font size, so it could look larger "
        "or smaller than the rest of the app — on macOS especially. All text now "
        "comes from the theme's type scale, in pixels, on every platform.",
        "Settings → Interface → Appearance → Text size scales all text (90%-150%), "
        "live, and is remembered.",
    ),
    test_steps=(
        "Open a series — its season/episode rows are the same size as the details "
        "pane's body text, not larger.",
        "Settings → Interface → Text size → Large (125%) → OK — every piece of text "
        "grows together, with no restart; set it back to Default — it returns.",
        "Restart — the chosen text size is still applied.",
    ),
)
