from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=565,
    version="0.86.0",
    date="2026-09-03",
    title="The source Auto-refresh setting now actually refreshes",
    items=(
        "Every source editor has had an \"Auto-refresh\" setting (Manual / On "
        "App Launch / Daily / Weekly / Every 30 Days) since early on — it saved "
        "your choice but nothing ever read it, so picking anything but Manual "
        "did nothing. It is wired up now.",
        "\"On App Launch\" refreshes that source's full catalog once, every "
        "time you open MetaTV. Daily/Weekly/Every 30 Days refresh on that "
        "interval while the app is open (checked hourly), always the same "
        "complete refresh the manual button runs — never a partial or "
        "category-only fetch.",
        "A source currently streaming is always skipped and retried on the "
        "next check, so an automatic refresh can never interrupt playback.",
        "Manual stays the default — nothing changes for existing sources "
        "unless you pick a different interval.",
    ),
    test_steps=(
        "Edit a source → Settings tab → hover the Auto-refresh dropdown → "
        "tooltip explains what each option does and the streaming-skip "
        "guarantee.",
        "Set a source to \"On App Launch\", restart MetaTV → that source's "
        "refresh queue runs automatically shortly after launch.",
        "Start playing a channel from a source set to auto-refresh, then wait "
        "for its interval to elapse → the source is skipped (check the logs "
        "for \"currently streaming\") until playback stops.",
    ),
)
