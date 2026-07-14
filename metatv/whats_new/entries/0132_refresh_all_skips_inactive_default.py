from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=132,
    version="0.9.0",
    date="2026-07-14",
    title="Refresh All now skips disabled sources by default",
    items=(
        "\"Refresh All\" no longer refreshes sources you've toggled off. Everywhere "
        "else a disabled source is already treated as hidden (it's scoped out of "
        "Browse, Discover, Recipes, EPG and recommendations), so spending connection "
        "budget and time re-fetching it on every Refresh All was the odd exception — "
        "now it's skipped.",
        "You can still refresh a single disabled source directly with its own refresh "
        "button — that's always a deliberate action and always works.",
        "Want the old behaviour back? Settings → Sources → \"Refresh inactive sources "
        "when refreshing all\" turns it on again.",
    ),
    test_steps=(
        "Disable a source in Sources, then run Refresh All: the disabled source is NOT "
        "enqueued (the refresh queue shows only enabled sources), and the log notes "
        "\"Refresh All: skipped N inactive source(s)\".",
        "Open Settings → Sources: \"Refresh inactive sources when refreshing all\" is "
        "unchecked by default. Check it, run Refresh All again, and the disabled source "
        "IS now enqueued.",
        "With the setting still off, click the individual refresh button on the disabled "
        "source itself: it refreshes normally (per-source refresh is unaffected).",
    ),
)
