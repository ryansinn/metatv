from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=63,
    version="0.9.0",
    date="2026-06-24",
    title="Cleaner series/movie titles: strip space-containing sub/dub qualifiers",
    items=(
        "Trailing subtitle and dub qualifiers like (ENG DUB), (SPANISH ENG-SUB), "
        "(DUAL AUDIO), and (VOST FR) are now stripped from card titles even when they "
        "contain spaces — the previous heuristic preserved any parenthetical with an "
        "internal space, leaving these suffixes visible on every card.",
        "Interior year tags that were hidden behind a qualifier — e.g. '(2025)' in "
        "'As Linas Descontinuas (2025) (SPANISH ENG-SUB)' — are now also removed once "
        "the qualifier is peeled off, so the final title is clean.",
        "Real alt-language titles in parentheses (e.g. '(Soleil Noir)', '(30 Monedas)') "
        "are preserved: stripping only happens when every token in the parenthetical is a "
        "recognized language, region, quality, or subtitle/dub marker.",
        "A one-time re-parse runs at launch to clean all stored titles in your library.",
    ),
    test_steps=(
        "Open Discover or a Show-All shelf. Find a card whose title previously ended with "
        "'(ENG DUB)', '(SPANISH ENG-SUB)', '(DUAL AUDIO)', or a similar dub/sub suffix "
        "— it should now display the clean title without that suffix.",
        "Find a title with a real alt-language title in parentheses, such as "
        "'30 Coins (30 Monedas)' or a show with '(Soleil Noir)' — confirm the parenthetical "
        "is still shown (it contains unrecognized words, so it must be preserved).",
        "Check a title that had a year hidden behind the qualifier, e.g. "
        "'As Linas Descontinuas (2025) (SPANISH ENG-SUB)' — the card should now read "
        "'As Linas Descontinuas' with both the qualifier and the year gone.",
        "At launch the first time after this update, a 'Cleaning channel title qualifiers' "
        "progress indicator may appear briefly — this is the one-time re-parse (version 2).",
    ),
)
