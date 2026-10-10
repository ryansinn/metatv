from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=708,
    version="0.148.0",
    date="2026-10-09",
    title="Alternate titles are kept and searchable",
    items=(
        "When your source files a movie under its regional release title "
        "(Innocent Blood as 'Oskyldigt blod'), Details shows it as 'Alternate title' "
        "and searching for it finds the movie.",
    ),
    test_steps=(
        "Open the SE copy of Innocent Blood — Details shows 'Alternate title  "
        "Oskyldigt blod · TREX Shared'.",
        "Search 'Oskyldigt' — Innocent Blood is in the results.",
    ),
)
