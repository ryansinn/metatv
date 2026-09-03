from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=574,
    version="0.91.0",
    date="2026-09-03",
    title="Sidebar sections wait out library updates instead of sitting empty",
    items=(
        "A library update pass (e.g. a rescan after upgrading) holds the "
        "database while it runs — sometimes for minutes on a large library. "
        "Sidebar sections used to submit their own background reads into "
        "that same contention, so Recommended could take 30+ seconds to "
        "show anything and every other section just sat empty with no "
        "explanation, while the extra reads slowed the update pass itself.",
        "Sections now say \"Waiting for the library update…\" instead of "
        "reading against the update, and load for real within a few "
        "seconds of it finishing.",
    ),
    test_steps=(
        "On a launch that runs a library update pass, sidebar sections say "
        "'Waiting for the library update…' and fill in within seconds of "
        "it finishing, instead of sitting empty for minutes.",
    ),
)
