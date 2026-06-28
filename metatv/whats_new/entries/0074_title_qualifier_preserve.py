from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=74,
    version="0.9.0",
    date="2026-06-27",
    title="Fixed titles losing real parentheticals like (Reprise) / (Unplugged)",
    items=(
        "Channel/movie/series titles no longer drop a trailing single-word "
        "parenthetical that is part of the real name — e.g. 'Welcome (Reprise)', "
        "'MTV Unplugged (Deluxe)', 'Cidade de Deus (Acoustic)' now keep their "
        "qualifier instead of being shortened to 'Welcome' / 'MTV Unplugged'.",
        "Genuine language/quality/sub-dub markers are still stripped as before: "
        "'(VOSTFR)', '(ENG-SUB)', '(DUBBED)', '(HQ)', '(US)' continue to be removed "
        "from the clean display title. The strip now checks the token against the "
        "recognized-qualifier vocabulary instead of removing any single word.",
        "Titles are computed at ingestion, so corrected titles appear after the "
        "affected source refreshes (or after a detected-title re-parse).",
    ),
    test_steps=(
        "Find content whose name ends in a real-word parenthetical that is NOT a "
        "language/quality marker (e.g. a song/version like '… (Reprise)', "
        "'… (Unplugged)', '… (Acoustic)', '… (Deluxe)'). Confirm the displayed "
        "title keeps the parenthetical rather than being cut off before it.",
        "Find content whose name ends in a real qualifier — '… (ENG-SUB)', "
        "'… (VOSTFR)', '… (DUBBED)', '… (HQ)'. Confirm that parenthetical is still "
        "stripped from the clean display title (unchanged behavior).",
        "Confirm a title with a parenthesized year (e.g. '… (2024)') still has the "
        "year removed from the display title (unchanged behavior).",
    ),
)
