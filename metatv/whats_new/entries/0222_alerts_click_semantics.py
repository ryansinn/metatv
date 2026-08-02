from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=222,
    version="0.19.0",
    date="2026-08-01",
    title="Double-click and \"Open series\" now browse monitored series in Watch Alerts",
    items=(
        "Double-clicking a monitored series in the Watch Alerts sidebar "
        "section (Movies & Series) used to behave exactly like a single "
        "click — it just loaded the series into the details pane. "
        "Double-click now actually browses into it, opening the season/"
        "episode tree — the same fix already shipped for the Watch Queue "
        "and Alerts Matched.",
        "The right-click \"Open series\" menu action had the identical bug "
        "— it also just loaded the details pane. It now browses into the "
        "series too.",
        "\"Mark seen\", \"Stop alerts\", and \"Manage…\" are unchanged in "
        "that same right-click menu.",
        "Hover a monitored series row to see the updated tooltip: "
        "double-click browses the series, right-click offers mark seen / "
        "stop.",
    ),
    test_steps=(
        "Monitor a series with new episodes → in Watch Alerts' Movies & "
        "Series list, double-click the row → the season/episode tree opens "
        "(not just the details pane), and the new-episode count clears.",
        "Right-click a monitored series row → choose \"Open series\" → the "
        "season/episode tree opens (not just the details pane).",
        "Single-click a monitored series row → the details pane updates "
        "with the series info (unchanged behavior).",
        "Right-click a monitored series row with new episodes → \"Mark "
        "seen\" clears the new-episode count without navigating away.",
        "Right-click a monitored series row → \"Stop alerts\" removes it "
        "from the monitored list.",
    ),
)
