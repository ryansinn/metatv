from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=529,
    version="0.72.0",
    date="2026-09-02",
    title="A Cast & Crew heading names one person, not the whole credits",
    items=(
        "Searching \"Strong\" headed a group with \"Paula Casarin, Carley "
        "Armstrong, Andrea Trigo, Martina Vazzoler, J.C. Chandor\" — the "
        "entire director field, because one name inside it matched.",
        "The heading now names just the person who matched. Where a value "
        "holds several names it picks the best one: an exact match first, "
        "then a whole-word one, preferring Mark Strong over Armstrong.",
    ),
    test_steps=(
        ("Search a surname several people share — \"Strong\" is a good one. "
         "Every Cast & Crew heading should be ONE name, never a comma-"
         "separated list.", "view:list"),
        ("Find a film whose credits list several people and confirm the "
         "heading names the one you searched for, not all of them.",
         "view:list"),
    ),
)
