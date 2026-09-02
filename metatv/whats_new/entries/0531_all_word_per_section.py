from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=531,
    version="0.72.0",
    date="2026-09-02",
    title="The section switch is now All | Word, and it works on Cast & Crew",
    items=(
        "Pressing the narrow option on Cast & Crew emptied the whole section. "
        "It was judging those rows by their TITLE, and a film listed under an "
        "actor does not have the actor's name in its title — so every one of "
        "them failed.",
        "Each section is now judged by the thing that put a row there: the "
        "title under Titles, the person under Cast & Crew. So narrowing Cast "
        "& Crew keeps Nicolas Cage and drops Beaucage, which is the whole "
        "point of the control.",
        "The two halves are relabelled All | Word. The old \"Part\" actually "
        "included the whole-word matches as well, so it read as the opposite "
        "of what it did; \"All\" says it plainly and \"Word\" says what the "
        "narrowing is.",
    ),
    test_steps=(
        ("Search an actor's surname, then press Word on the Cast & Crew "
         "section. It must NOT empty — you should keep the people whose name "
         "is that word and lose the ones who merely contain it.", "view:list"),
        ("Press Word on Titles with a search like \"Tron\" and confirm "
         "Astronaut goes while Tron stays.", "view:list"),
        ("Confirm each section starts on All, and that pressing Word on one "
         "leaves the other alone.", "view:list"),
        ("Press All again on both and confirm every result returns.",
         "view:list"),
    ),
)
