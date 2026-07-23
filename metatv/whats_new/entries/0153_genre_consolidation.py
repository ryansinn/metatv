from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=153,
    version="0.10.0",
    date="2026-07-22",
    title="Consolidated ~500 messy genre labels into ~40 canonical genres",
    items=(
        "The GENRE filter used to sprawl into hundreds of near-duplicate values — "
        "typos ('Dram', 'DRMA', 'Thrille'), case/spacing variants, format-word "
        "noise ('Drama series', 'Reality Show'), and the same genre in dozens of "
        "languages. An owner-approved consolidation now folds 129 of those raw "
        "spellings into their canonical genre, on top of the multilingual folds "
        "already in place, so the panel shows one clean entry per genre with the "
        "combined count.",
        "Ten new canonical genres join the vocabulary: Adult, Politics, Biography, "
        "Game Show, Anime, Music Show, TV Movie, and the Drama-led compounds "
        "Drama & Comedy, Drama & Crime, and Drama & Romance.",
        "'Soap' is now displayed as 'Soap Opera' (telenovelas fold in), and a few "
        "old mis-mappings were corrected: Biography no longer lands under History, "
        "'competition/tävling' is now Game Show, and 'children & family' is Family.",
        "Consolidation is deliberately conservative: compounds stay first-class "
        "(never split into their parts), and anything not confidently a spelling "
        "variant is left raw and still visible. Every fold is documented in "
        "docs/GENRE_MAPPING.md.",
        "A one-time background pass re-tags your existing channels so the merge "
        "takes effect without a manual refresh. Your favorites, ratings, queue, "
        "history, and hand-added tags are untouched.",
    ),
    test_steps=(
        "Open the filter panel and expand the GENRE section → the number of genre "
        "entries is dramatically smaller than before (~40 canonical genres plus a "
        "small raw tail, not 500+ near-duplicates).",
        "Find an item whose provider genre was the typo 'Dram' → it now shows and "
        "filters under 'Drama' (selecting 'Drama' includes it).",
        "Look for Arabic 'program'/'serial' content (e.g. برنامج / سریال) → those "
        "items now appear under the single 'TV Show' genre, not as separate "
        "Arabic-script entries.",
        "Confirm the genre formerly shown as 'Soap' now reads 'Soap Opera', and "
        "that a telenovela-tagged item filters under it.",
        "Confirm a deliberately-kept oddball genre (e.g. 'Sitcom', 'Stand Up', or a "
        "mixed-language multi-genre string) is still visible as its own raw value — "
        "it was NOT force-folded.",
        "Open docs/GENRE_MAPPING.md → any fold you see in the panel is explained "
        "there (raw value → canonical → why), and the keep-as-is tail is listed.",
    ),
)
