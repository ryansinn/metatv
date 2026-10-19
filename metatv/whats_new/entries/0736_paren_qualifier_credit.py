from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=736,
    version="0.173.0",
    date="2026-10-19",
    title="Titles like \"Anger Management (2012) (US) CHARLIE SHEEN\" are cleaned",
    items=("A name with a year, then a note in brackets, then an actor in capitals — "
           "\"Anger Management (2012) (US) CHARLIE SHEEN\", \"Podium (2004) (FRENCH ENG-SUB) "
           "JEAN PAUL ROUVE\" — kept all of it in its title. The title is now just \"Anger "
           "Management\", with the year, region and actor read out as usual. 860 titles in a "
           "large library had this; existing ones are re-read once on the next launch.",),
    test_steps=("After the one-time re-read on launch, search for \"Anger Management\" — the row "
                "reads \"Anger Management\" with 2012, not the bracketed tail and the actor's name.",),
)
