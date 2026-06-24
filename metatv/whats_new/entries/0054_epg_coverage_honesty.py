from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=54,
    version="0.9.0",
    date="2026-06-24",
    title="EPG: honest guide coverage (filler no longer fakes 'good through')",
    items=(
        "Fixed: multi-day filler placeholder entries (e.g. a 3-day 'Program' slot) no "
        "longer inflate the guide-depth indicator. The provider's EPG status now reflects "
        "the real schedule depth — e.g. 'good through tonight' instead of 'good through Jun 27'.",
        "EPG Browse empty state now explains exactly how far the active source's guide "
        "reaches when a time slot has no programmes, so an empty prime-time slot reads "
        "as 'guide currently reaches <date/time>' rather than a bare empty list.",
        "Clear-search button in EPG Browse now matches the main search bar style.",
    ),
    test_steps=(
        "Open EPG Browse → select Today → Prime Time — if the source guide ends tonight, "
        "the empty state should say 'guide currently reaches <time>' rather than the generic "
        "'No programmes for the selected day and time.'",
        "Check the sidebar EPG indicator (or Provider editor) for a source with multi-day "
        "filler: it should now show an accurate depth (e.g. 'ends tonight') rather than a "
        "far-future 'good through' date inflated by filler programmes.",
        "Type in the EPG Browse search box then click × — the search clears; the × button "
        "style matches the main channel-list search bar.",
    ),
)
