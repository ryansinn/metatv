from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=219,
    version="0.18.1",
    date="2026-08-01",
    title="What's New keeps upgrade notes short",
    items=(
        "If many releases piled up unseen, the automatic What's New dialog now "
        "shows only the newest release's entries, with a note counting the "
        "older ones — the full history stays in Help ▸ What's New.",
    ),
    test_steps=(
        "Set last_seen_whats_new_id very low in config.yaml (e.g. 5), launch → "
        "the auto dialog shows only the newest release's entries plus a footer "
        "note counting the earlier ones.",
        "Help ▸ What's New → the full changelog is still all there.",
    ),
)
