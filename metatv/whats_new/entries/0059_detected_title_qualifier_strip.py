from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=59,
    version="0.8.0",
    date="2026-06-24",
    title="Clean channel titles — strip quality/region/subtitle suffixes",
    items=(
        "Channel titles no longer show trailing quality, region, or subtitle qualifiers "
        "like (HQ), (4K), (VOSTFR), or (US). These are stripped at ingestion so titles "
        "read cleanly in all surfaces.",
        "Variants that differed only by those suffixes (e.g. '1883 (VOSTFR)' vs '1883') "
        "now share the same content identity and collapse to a single card in Recipe "
        "and Discover browse.",
        "Alt-language titles with a space inside the parens (e.g. '(Soleil Noir)', "
        "'(30 Monedas)') are preserved and continue to appear as separate cards.",
        "A one-time background migration re-parses all existing channels on first launch "
        "after this update.",
    ),
    test_steps=(
        "Open Recipe or Discover → Show All → scroll through titles: no card should show "
        "a trailing qualifier like (HQ), (4K), (LQ), (VOSTFR), or (US) in the title.",
        "Search for '1883' in Show All: if your source has both 'FR - 1883 (VOSTFR)' and "
        "'EN - 1883 (2021)', both should show detected_title '1883' and appear as a single "
        "collapsed card (same content_key).",
        "Find a title with a multi-word alt-language title in parens, e.g. "
        "'30 Coins (30 Monedas)': the '(30 Monedas)' portion must still appear in the title.",
        "Check the migration progress widget at launch: 'Cleaning channel title qualifiers' "
        "should complete without error and not appear again on the next restart.",
    ),
)
