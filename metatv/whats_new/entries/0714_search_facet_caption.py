from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=714,
    version="0.154.0",
    date="2026-10-10",
    title="Search results show their facet above the name",
    items=("Each result of 'Search tags across all facets' carries a small caps caption "
           "(CAST, DIRECTING, GENRE…) above the name.",),
    test_steps=("In Recipe, search 'wyler' — Maud Wyler is captioned CAST and William Wyler "
                "DIRECTING; clicking either still adds it to the recipe.",),
)
