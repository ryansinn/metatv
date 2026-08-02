from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=220,
    version="0.18.2",
    date="2026-08-01",
    title="Stream recovery is now visible and one click away",
    items=(
        "A stream that failed and later came back online now stays listed in "
        "the sidebar's Stream Monitoring section with a green \"back online\" "
        "icon, instead of silently disappearing the moment it recovers.",
        "The \"back online\" toast now has a Play button that launches the "
        "recovered stream immediately — no need to hunt it down in the sidebar.",
    ),
    test_steps=(
        "Trigger a stream failure (or wait for one), then let the background "
        "retry checker mark it back online — the Stream Monitoring row switches "
        "to a green icon and a \"Back online!\" tooltip and stays visible.",
        "When the \"Stream Available\" toast appears, click its Play action — "
        "the stream launches immediately.",
        "Right-click the recovered row → Remove — it disappears from the list.",
    ),
)
