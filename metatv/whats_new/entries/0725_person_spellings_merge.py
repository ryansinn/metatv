from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=725,
    version="0.163.0",
    date="2026-10-11",
    title="Different spellings of the same person are one person",
    items=("'Denzel Washigton' and 'Denzel Washington', 'Andy Garcia' and 'Andy García', "
           "'Matthew McConaughey' and 'Mcconaughey' — about 930 spellings — now merge into "
           "one person each, so search, the Cast cloud and recipes find all their titles.",
           "A spelling seen once is remembered, so a provider sending it again lands on the "
           "same person.",
           "A one-time pass merges your existing names (about half a minute)."),
    test_steps=("Restart and let 'Merging spellings of the same person' finish.",
                "In Recipe search 'denzel' — one Denzel Washington, no 'Washigton'.",
                "Search 'garcia' — one Andy Garcia."),
)
