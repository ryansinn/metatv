from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=64,
    version="0.9.0",
    date="2026-06-24",
    title="Cleaner titles: strip language+sub/dub qualifiers with unrecognized language words",
    items=(
        "Trailing subtitle and dub annotations that pair an unknown language word with an "
        "unambiguous marker — e.g. '(JAPANESE ENG-SUB)', '(PERSIAN SUB)', '(KURDISH DUB)', "
        "'(NORWEGIAN SUB)', '(CHINESE ENG-SUB)' — are now stripped from card titles. "
        "The previous heuristic only stripped qualifiers when every token was in the "
        "recognized vocabulary, leaving ~170 distinct language+sub patterns unstripped.",
        "The new rule is anchored on an unambiguous sub/dub marker (SUB, SUBS, SUBBED, "
        "SUBTITLED, DUB, DUBBED, VOST, VOSTFR, LEG, LEGENDADO, MULTISUB, ENGSUB). "
        "Any all-alphabetic parenthetical containing one of these markers is treated as a "
        "qualifier annotation and removed from the display title.",
        "Real alt-language titles and other parentheticals are preserved: the all-alphabetic "
        "guard means anything with a digit (e.g. '(Episode 5 SUB)', '(30 Monedas)') is kept, "
        "as are parentheticals with no unambiguous marker (e.g. '(Reprise)', '(The Awakening)').",
        "A one-time 'Cleaning channel title qualifiers' migration runs at launch to clean all "
        "stored titles in your library.",
    ),
    test_steps=(
        "Open the channel list or a Discover shelf. Find a title that previously ended with a "
        "language+sub qualifier like '(JAPANESE ENG-SUB)', '(PERSIAN SUB)', or '(KURDISH DUB)'. "
        "After this update, the title card should show the clean title without that suffix.",
        "At first launch after this update, a brief 'Cleaning channel title qualifiers' progress "
        "indicator may appear — this is the one-time version-3 re-parse updating all stored titles.",
        "Search for a show you know has a language+SUB suffix in its IPTV name (e.g. search for "
        "the show name without the suffix). Confirm the result appears with the clean title and "
        "that the card's detected_title no longer contains the parenthetical.",
        "Verify no false positives: check that '(Reprise)', '(Episode 5 SUB)', and real "
        "alt-title parentheticals containing digits are still present on cards that should "
        "keep them.",
    ),
)
