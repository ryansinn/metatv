from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=533,
    version="0.73.0",
    date="2026-09-02",
    title="A fixture row now says whether it is on now or already over",
    items=(
        "A game that had finished looked exactly like one that was on. The "
        "only way to find out was to click it — and because the provider "
        "reuses the slot, you were served whatever is on that channel now "
        "rather than the game named on the row.",
        "Rows for dated fixtures now carry a state mark: a green \"On now\" "
        "while the scheduled window is running, a quiet \"Ended\" once it has "
        "passed. It leads the row's meta line, because for a fixture that is "
        "the fact you are actually scanning for.",
        "It only appears where a real time backs it up. The provider's own "
        "LIVE label is wrong on 99% of rows, so nothing here reads it — the "
        "mark comes from the parsed start and end times. Nothing changes on "
        "the ~96% of the library that is not a dated event, and an upcoming "
        "fixture gets no mark: a schedule already says it is later.",
        "The list re-checks itself once a minute, so \"On now\" cannot "
        "outlive the game while you are looking at it.",
    ),
    test_steps=(
        ("Open Sports and pick the On now lane. Every row must carry the "
         "green On now mark — and no row in that lane may say Ended.",
         "view:sports"),
        ("Switch to the Finished lane. Those rows must read Ended, in the "
         "quiet neutral style — not a second block of colour.", "view:sports"),
        ("Switch to Upcoming and confirm rows carry NO state mark at all.",
         "view:sports"),
        ("Search for an ordinary movie and confirm its row has no state mark "
         "— this is for dated fixtures only.", "view:list"),
        ("Leave the Sports list open across the moment a fixture's window "
         "ends; within a minute the row should flip from On now to Ended "
         "without you touching anything.", "view:sports"),
        ("Switch theme to Daylight and confirm the On now chip's text is "
         "still readable on its green fill.", "view:sports"),
    ),
)
