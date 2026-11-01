from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=788,
    version="0.224.0",
    date="2026-11-01",
    title="\"(SUB)\", \"(DUB)\" and other tags in a name are no longer read as a region",
    items=("A title ending in \"(SUB)\" or \"(DUB)\" was filed under a region called SUB or DUB "
           "(over 1,100 titles); now it is marked as subtitled or dubbed. Codes MetaTV doesn't know "
           "— \"(DOC)\", \"(BK)\", team codes like \"[TOR]\" — are no longer turned into regions, and "
           "\"[SPA]\", \"(PNJ)\" and \"(VFQ)\" are read as Spanish, Punjabi and Quebec French. Existing "
           "titles are corrected on the next launch.",),
    test_steps=("Launch MetaTV — the startup tasks include \"Clearing region codes nothing can name\".",
                "Open the region filter — there is no SUB, DUB, DOC or BK region.",
                "Find a title ending in \"(SUB)\" — its details show it as subtitled.",),
)
