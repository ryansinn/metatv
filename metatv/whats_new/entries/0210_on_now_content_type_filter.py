from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=210,
    version="0.18.0",
    date="2026-08-01",
    title="EPG On Now: filter by content type",
    items=(
        "A new \"All Types ▼\" dropdown next to Category in the On Now tab lets "
        "you narrow the list to Sports, News, Kids, Movies, or Music (plus "
        "Other for anything unclassified).",
        "Channels are classified from their name — a channel whose Category is "
        "already Sports/News/Kids/Music counts directly; everything else is "
        "matched by keyword (sport/league names reuse the same list Special "
        "Content sports detection already uses, so there's one definition, "
        "not two).",
        "The type filter composes with search and the existing Category "
        "dropdown, and your selection is remembered across restarts.",
    ),
    test_steps=(
        ("Open the On Now tab in EPG — an \"All Types ▼\" dropdown appears "
         "next to Category, checked to all types by default.", "view:epg"),
        "Uncheck all but \"Sports\" in All Types — only sports channels remain "
        "visible; type something in Search — the list narrows further within "
        "Sports.",
        "Restart the app and reopen On Now — the All Types selection you left "
        "it on is still applied.",
    ),
)
