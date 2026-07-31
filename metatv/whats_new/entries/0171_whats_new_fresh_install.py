from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=171,
    version="0.13.0",
    date="2026-07-31",
    title="A fresh install no longer replays the entire What's New history",
    items=(
        "On a brand-new install, MetaTV no longer opens the What's New dialog with "
        "every past release to click through — a first launch now starts caught up. "
        "Existing users still see genuinely new entries after each update.",
    ),
    test_steps=(
        "With no existing config (a fresh install, or move ~/.config/metatv aside), "
        "launch MetaTV: the What's New dialog does NOT auto-appear on first run.",
        "Confirm Help → What's New still opens the full changelog on demand.",
    ),
)
