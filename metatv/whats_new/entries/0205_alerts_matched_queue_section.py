from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=205,
    version="0.17.0",
    date="2026-08-01",
    title="\"Alerts Matched\" section in the Watch Queue",
    items=(
        "The Watch Queue sidebar now has a topmost \"Alerts Matched\" section: "
        "one row per unviewed watch-for match, plus one row per series you're "
        "monitoring with new episodes — no more digging through the transient "
        "banner to see what fired.",
        "Each matched row carries a green \"NEW\" tag; hover to see which of "
        "your alerts it matched (e.g. \"Matched your alert: 'masters'\").",
        "Click a matched-channel row to open its details AND acknowledge the "
        "match everywhere else (banner count, Watch Alerts section) in one "
        "step. Click a matched-series row to open the series — same as the "
        "Watch Alerts section's series rows.",
        "The section persists across restarts — it's derived from your "
        "existing watch-for and monitored-series state, no new data to lose.",
    ),
    test_steps=(
        "Add a 'Watch for…' keyword rule that matches an existing title → the "
        "Watch Queue sidebar shows a topmost 'Alerts Matched' section with a "
        "green NEW row for the match.",
        "Hover the matched row → tooltip reads \"Matched your alert: "
        "'<keyword>'\".",
        "Click the matched row → the details pane opens for that title, and "
        "the row disappears from Alerts Matched (and the pinned banner count "
        "drops) on the next refresh.",
        "Monitor a series and simulate a new episode (unseen_new > 0) → a "
        "distinct 🆕 series row appears in Alerts Matched; clicking it opens "
        "the series in the details pane.",
    ),
)
