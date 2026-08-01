from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=203,
    version="0.17.0",
    date="2026-08-01",
    title="Series monitor: recurring checks, multi-source detection",
    items=(
        "Monitored series (\"Alert me to new episodes\") are now rechecked "
        "automatically while the app is running, not just at startup or after "
        "a source refresh — a background timer re-runs the check on an "
        "interval (default hourly; configurable, 0 = off).",
        "If the same show is carried by more than one of your sources, a new "
        "episode landing on ANY of them now triggers the alert — previously "
        "only the specific source you clicked \"Alert me\" from was checked. "
        "The toast and the Watch Alerts row tooltip now name which source the "
        "new episode(s) came from (e.g. \"2 new eps on ProSat\").",
        "Opening a monitored series' season/episode list (drilling in) now "
        "clears its \"new\" badge automatically, the same as using \"Mark "
        "seen\" — you no longer have to separately dismiss it after actually "
        "watching what's new.",
        "The Watch Alerts sidebar section shows a subtle \"checking…\" hint "
        "next to Movies & Series while a recheck pass is running, so a source "
        "going quiet or slow is visible instead of the list silently changing "
        "underfoot.",
    ),
    test_steps=(
        "With at least one series monitored, leave the app open past the "
        "default 60-minute recheck interval and confirm a background recheck "
        "runs on its own (no source refresh or restart needed) — check the "
        "app log for a 'series_monitor: recurring recheck' line at launch.",
        "Monitor a series that exists on two of your sources under the same "
        "title/year; when a new episode appears on the source you did NOT "
        "originally alert from, confirm the Watch Alerts badge still "
        "increments and the row's tooltip names that source.",
        "With a series showing a \"+N eps\" badge in Watch Alerts, click it to "
        "drill into its season/episode list; confirm the badge clears without "
        "using the right-click \"Mark seen\" action.",
        "Trigger a manual source refresh (or wait for the recurring timer) "
        "and confirm the Watch Alerts header briefly shows a \"checking…\" "
        "hint next to Movies & Series while the recheck runs.",
    ),
)
