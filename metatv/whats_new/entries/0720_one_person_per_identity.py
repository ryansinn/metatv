from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=720,
    version="0.159.0",
    date="2026-10-10",
    title="One person, whatever their role",
    items=("Actors, directors and names written in a title are now one person each — "
           "searching Cillian Murphy finds one Person covering every title he is "
           "attached to, instead of separate Cast and Person entries.",
           "Picking a Person in a recipe matches them in any role; the Cast and "
           "Directing clouds still narrow to that role.",
           "'Uncredited' is no longer part of a name.",
           "A one-time pass merges your existing credits (about half a minute)."),
    test_steps=("Restart and let 'Merging cast and directors into one person each' finish.",
                "In Recipe, search 'cillian' — one Person 'Cillian Murphy'; add it — the "
                "results include films where his name is only in the title.",
                "Open a film Clint Eastwood directed and starred in — he shows under Cast "
                "and Directing."),
)
