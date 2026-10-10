from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=702,
    version="0.142.0",
    date="2026-10-09",
    title="Spanish, not ES-ES — and episodes with commas queue again",
    items=(
        "Stream languages reported as region codes (es-ES, pt_BR) now read as "
        "the language — Spanish, Portuguese — and merge with the guessed one; "
        "subtitle tracks show their own names (Completos / Completos CC).",
        "Episodes whose titles contain a comma (\"A rey muerto, rey puesto\") were "
        "silently left out of the play queue. They now queue, and a queue that "
        "mpv refuses is reported instead of counted as done.",
    ),
    test_steps=(
        "Play an episode of a Spanish series, reselect it — Details reads Audio "
        "'Spanish E-AC-3 5.1', Subtitles 'Spanish SRT (Castellano (Completos)) · …', "
        "and Language lists Spanish once.",
        "Play S01E01 of 'La vida breve' — the mpv playlist holds all six episodes, "
        "including E2 and E5.",
    ),
)
