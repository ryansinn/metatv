from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=138,
    version="0.9.0",
    date="2026-07-21",
    title="Fixed mislabeled prefixes: AR = Arabic (not Argentina), BS = Balkan, Panama vs Punjabi",
    items=(
        "The 'AR' prefix is now correctly treated as Arabic everywhere (it was "
        "decisively Arabic in your library — 90k+ channels). It no longer shows "
        "'Argentina' in the details pane, and it no longer appears under Spanish, "
        "South America, or Latin America filters. Real Argentine content uses "
        "'ARG' and is unaffected.",
        "'BS' channels (Balkan / 'Balkan Sky' — Serbian/Croatian) are no longer "
        "grouped under English.",
        "'PA' now means Panama (Spanish) and 'Punjabi' now maps to its own code "
        "'PB'. Panama channels (PA| RPC, PA| TELEMETRO) are no longer mislabeled "
        "as Indian, and Punjabi channels correctly classify as Indian/Punjabi.",
        "A one-time background pass re-scans and re-tags your existing channels so "
        "the corrections take effect without a manual full refresh. Your favorites, "
        "ratings, queue, history, and hand-added tags are untouched.",
        "Added a regression guardrail so these four interpretation tables "
        "(filter groups, classification, display names) can't silently drift apart "
        "again.",
    ),
    test_steps=(
        "Open an Arabic 'AR' title (e.g. one called 'The Odyssey') in the details "
        "pane → the region line shows 'AR' (or Arabic context), and the word "
        "'Argentina' does NOT appear anywhere in the pane.",
        "Add 'Arabic' to Exclusions → the AR title disappears from the list; an "
        "'ARG' / Argentine-Spanish title stays visible (Arabic exclusion must not "
        "hide Argentine content).",
        "Filter/browse 'South America' or 'Spanish' → Arabic 'AR' channels are NOT "
        "listed there; 'ARG' Argentine channels still are.",
        "Find a 'BS |' channel (Balkan Sky / Serbian-Croatian) → it classifies as "
        "Serbian/Croatian, not English.",
        "Find a 'PUNJABI |' channel → it classifies as Indian (Punjabi). Find a "
        "'PA |' channel (e.g. PA| RPC, PA| TELEMETRO) → it classifies as Spanish / "
        "Panama, not Indian.",
    ),
)
