from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=790,
    version="0.226.0",
    date="2026-11-01",
    title="Two follow-ups to the episode grouping and studio clean-up",
    items=("Episodes named with both a season marker and an episode count (\"Konusanlar S02E04 76. "
           "Bolum\") now group with the rest of their show instead of standing alone.",
           "A few more studio names stop showing up as people (\"Sithara Entertainments\", "
           "\"Ánima Estudios\", \"W-Pictures\"). Both are applied on the next launch.",),
    test_steps=("Launch MetaTV, then search for \"Konusanlar\" in Movies — one card for the show.",
                "Filter by person — no \"… Entertainments\" or \"… Estudios\" names.",),
)
