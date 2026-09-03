from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=561,
    version="0.86.0",
    date="2026-09-03",
    title="Sports fixture rows are now named by their matchup",
    items=(
        "Sports/PPV fixture rows previously showed the raw provider slot "
        "string as their title (e.g. \"(FLSP 246) | live: Ireland vs "
        "England _ Women's Cricket (2026-09-03 08:00:00)\"). They now show "
        "just the matchup — \"Ireland vs England\" — reusing the opponents "
        "already parsed for the Team facet.",
        "The AWAY-@-HOME provider convention (\"Lakers @ Celtics\") reads "
        "as \"Lakers at Celtics\", not \"Lakers vs Celtics\".",
        "A fixture with no named opponent (a single-event race, a racing "
        "venue listing) gets a cleaned single-event title instead, or is "
        "left as-is when nothing usable survives — the raw provider string "
        "always remains available on the row's tooltip.",
        "Existing fixtures are retitled automatically at next launch via "
        "the sports reclassify pass, which also recomputes their collapse "
        "key so a retitled fixture doesn't lose its cross-source grouping.",
    ),
    test_steps=(
        "Find a Sports row whose raw name has a clear \"Team A vs Team B\" "
        "shape — the list now shows just the matchup as its title.",
        "Find an AWAY-@-HOME row (e.g. an NBA slot named \"Lakers @ "
        "Celtics\") — its title reads \"Lakers at Celtics\".",
        "Find a Sports row with no opponent (a single-event race/venue "
        "listing) — its title is either a cleaned single-event name or "
        "unchanged, never a mangled fragment.",
        "Hover a retitled fixture row — the tooltip still shows the raw "
        "provider name.",
    ),
)
