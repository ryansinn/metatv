from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=692,
    version="0.137.0",
    date="2026-10-09",
    title="The language you actually hear comes first",
    items=(
        "Once a copy has been played or probed, its Details Language row lists "
        "the languages heard in the stream first; a language implied by the "
        "region (e.g. Swedish for an SE copy) stays below, marked as a guess.",
    ),
    test_steps=(
        "Open the SE copy of a film that plays in English, after playing or probing "
        "it — Language reads 'English · seen when played …' then "
        "'Swedish · guessed from region Sweden (SE)'.",
    ),
)
