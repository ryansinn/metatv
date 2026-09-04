from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=581,
    version="0.94.0",
    date="2026-09-03",
    title="Excluded regions now catch channels labeled only by their category",
    items=(
        "Channels whose region lived only in the provider category prefix "
        "(e.g. \"AR| BEIN SPORTS NX\" carrying unprefixed \"BEIN SPORTS\" "
        "names) now inherit that region at ingestion — the channel's own "
        "name-prefix always wins, the category only fills the gap.",
        "About 8,800 rows that escaped Global Exclusions this way (AR, GR, "
        "BR, NL, DE and others) are caught after the next refresh.",
    ),
    test_steps=(
        "With AR excluded in Global Exclusions, refresh a source → the "
        "'AR| BEIN SPORTS NX' channels no longer appear in Sports/search/"
        "Discovery.",
        "A 'UK|'-named channel inside an AR category still shows under UK "
        "rules (name wins).",
    ),
)
