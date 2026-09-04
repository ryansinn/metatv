from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=582,
    version="0.94.0",
    date="2026-09-03",
    title="FLO football events are now filed under the right football",
    items=(
        "Inside FLO categories, a bare '| football:' title now classifies as "
        "American football instead of soccer — 'football' elsewhere still "
        "means soccer (Premier League feeds and the rest of the vocabulary "
        "are untouched).",
        "This is the first context-scoped keyword: the same "
        "specific-beats-global precedence the region rules already use, now "
        "applied to sport keywords.",
        "A one-time repair pass at next launch relabels the ~73 affected "
        "events, which were previously filed under Soccer.",
    ),
    test_steps=(
        "After the launch repair, Sports → Football contains the FLSP "
        "'| football:' college games; the Soccer chip does not.",
        "A 'FOOTBALL' channel in a UK/soccer category still files under "
        "Soccer.",
    ),
)
