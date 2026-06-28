from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=97,
    version="0.9.0",
    date="2026-06-28",
    title="Recommendations & Similar Titles: localized-title and MULTI variants now merge",
    items=(
        "Recommendations and the details-pane 'Similar Titles' list now collapse "
        "duplicates using the same stored identity key the rest of the app uses — so a "
        "production that appears under different titles (e.g. an English and a "
        "Scandinavian name) shows as ONE entry instead of two.",
        "'MULTI' (multi-audio) source variants now merge with their plain siblings "
        "everywhere variants are grouped (Browse counts, Discover, Other Versions, "
        "Recommendations, Similar): a bare trailing 'MULTI'/'MULTI SUB' tag is ignored "
        "when computing a title's identity. Real titles like 'Multiplicity' or 'Dual "
        "Survival' are left untouched.",
        "Existing channels are re-keyed automatically on next launch (a one-time "
        "background recompute of the identity key — your tags, ratings, favorites, and "
        "queue are not touched).",
    ),
    test_steps=(
        "Find a movie/series that has both an English and a localized (e.g. "
        "Scandinavian) titled copy across your sources. Confirm Recommendations shows it "
        "ONCE (hover the entry — the tooltip should say 'N versions grouped').",
        "Open a title whose sources include a 'MULTI' copy (e.g. 'Show Name MULTI'). In "
        "the details pane, confirm the MULTI copy appears under 'Other Versions' / the "
        "source picker rather than as a separate Similar Title.",
        "Open the details pane for a popular title and confirm the 'Similar Titles' list "
        "no longer lists the same production twice under slightly different names.",
        "Restart the app once and confirm it still starts normally (the content-key "
        "recompute runs in the background); spot-check that a previously-duplicated "
        "title now collapses in Recommendations.",
    ),
    addresses=("flagged:1ebe93bb-f990-4c79-99a1-ba3c1ffeae85",),
)
