from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=585,
    version="0.95.0",
    date="2026-09-04",
    title="Watch rules match words in any order",
    items=(
        "A watch rule set to Any word or All words now matches that way in "
        "its list of programmes, on both the Watch Alerts sidebar and the "
        "EPG Watchlist tab — before, the rule's own count was right but the "
        "rows beneath it silently fell back to the exact consecutive phrase.",
        "Exclude terms now suppress rows on both surfaces, so the "
        "\"suppressed by excludes\" count and the list finally agree.",
        "The Description toggle on a rule shows how many more programmes "
        "turning it on would find, e.g. \"Description (24)\" — the count "
        "disappears once the toggle is on.",
        "Existing rules keep their exact behaviour: whole-word Phrase "
        "matching is stamped explicitly, never inherited by default.",
    ),
    test_steps=(
        "Edit a rule with two terms, set Match to Any word → a programme "
        "titled with the words in reverse order now appears in its "
        "upcoming list (sidebar and Watchlist tab alike).",
        "Add one of that programme's words as an exclude term → the row "
        "disappears and the summary line's suppressed count goes up by one.",
        "With Description off on a rule whose term appears only in some "
        "programme descriptions, the Description chip shows a (N) badge → "
        "turn it on → N more programmes appear and the badge clears.",
    ),
)
