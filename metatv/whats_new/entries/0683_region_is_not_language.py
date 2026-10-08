from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=683,
    version="0.130.0",
    date="2026-10-08",
    title="A catalogue's region is no longer read as the film's language",
    items=(
        "A film or series filed under a regional catalogue like |SE| keeps its "
        "region, and the language that region suggests is kept only as a "
        "low-confidence guess so you can still find it, ranked below anything "
        "that actually states the spoken language; live channels are unchanged.",
    ),
    test_steps=(
        "Open a film from |SE| FILM 1900 - 2018 — its tags show Region Sweden, "
        "and Swedish only as a low-confidence language.",
        "Search the tag cloud / recipe builder for 'Swedish' — the SE film "
        "catalogue still appears.",
        "Open a live channel with a country prefix (e.g. a DE: channel) — its "
        "language tag is unchanged.",
    ),
)
