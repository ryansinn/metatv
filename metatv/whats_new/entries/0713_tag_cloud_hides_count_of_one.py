from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=713,
    version="0.153.0",
    date="2026-10-10",
    title="Tag clouds drop the '1'",
    items=("A tag on a single title shows just its name — no '1' after it. The tooltip "
           "still says '1 channel'.",),
    test_steps=("In Recipe, search 'wyler' — William Wyler shows no number; Noah Wyle still "
                "shows 7. Hover William Wyler — the tooltip reads '1 channel'.",),
)
