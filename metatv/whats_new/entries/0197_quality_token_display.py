from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=197,
    version="0.15.0",
    date="2026-08-01",
    title="'RAW' and 'HEVC' now read as what they actually mean",
    items=(
        "Not every quality label a source stamps on a channel is a picture-quality "
        "tier. 'RAW' means an untranscoded, high-bitrate feed — not a bad or "
        "unfinished one — so it now reads as 'Uncompressed' wherever quality is "
        "shown: the On Now Quality column, the details-pane chip, filter chips, "
        "channel-list rows and the sidebar rows.",
        "'HEVC' keeps its short name (that IS what it's called) but now explains "
        "itself on hover: it's an efficient video codec, not a quality tier — so it "
        "no longer looks like something that should rank against 4K or HD.",
        "This is a labelling change only. The stored value never changes, so your "
        "saved filters, recipes and Global Exclusions keep selecting exactly what "
        "they selected before — the 'RAW' filter group still filters RAW.",
    ),
    test_steps=(
        "Open the EPG On Now tab and find a channel whose Quality column showed "
        "'RAW'. Confirm it now reads 'Uncompressed', and hover it — the tooltip "
        "explains it's an untranscoded source feed, not a resolution tier.",
        "Find a channel whose quality is 'HEVC' and hover the Quality cell: the "
        "tooltip says it's an efficient codec, not a picture-quality tier. The cell "
        "text still reads 'HEVC'.",
        "Open the filter panel's Quality section: the 'RAW' entry is labelled "
        "'Uncompressed'. Tick it and confirm it still filters the same channels as "
        "before (the label changed, the filter did not).",
        "Select a RAW title and check the details pane — the quality chip beside the "
        "title reads 'Uncompressed' with the explaining tooltip. Confirm a normal "
        "tier (4K / HD / SD) is displayed exactly as before, unchanged.",
    ),
)
