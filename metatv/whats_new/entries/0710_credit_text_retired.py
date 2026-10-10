from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=710,
    version="0.150.0",
    date="2026-10-10",
    title="Cast and directors are read from one index",
    items=(
        "Everything that shows or uses cast and directors — Details, search, the "
        "person filter, recommendations, Similar Content — now reads one index. "
        "The old per-title copies are removed after a final verified pass "
        "('Finishing the cast & title index' on next launch).",
    ),
    test_steps=(
        "Launch — 'Finishing the cast & title index' runs once in the background.",
        "Open a film with cast — the Cast section lists the same people in billing order.",
        "Click a cast member — the list filters to their titles; search their name — "
        "the result explains the match with their name.",
        "Recommendations still show 'with <actor>' reasons for people you like.",
    ),
)
