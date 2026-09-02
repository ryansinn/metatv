from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=523,
    version="0.70.0",
    date="2026-09-02",
    title="Search results say why they are on screen",
    items=(
        "Ranking put the right things first, but a search for \"Tron\" still "
        "mixed twelve real Tron titles into ninety-odd films that merely have "
        "a Trond or a Katrine Tronstad in the credits, with nothing to tell "
        "you which was which.",
        "Results are now grouped under two headings — Titles, then Cast & "
        "Crew — so a row that is on screen because of somebody in the credits "
        "says so instead of looking like a mistake.",
        "Neither section starts collapsed and nothing is hidden. If you were "
        "searching for an actor, their films are right there without a click.",
        "Grouping only happens while you are searching. Clearing the box puts "
        "the list back exactly as you had it, including your own Group-by-type "
        "setting, which a search no longer changes.",
    ),
    test_steps=(
        ("Search for a name that is also a word fragment — \"Tron\" or "
         "\"Cage\". Confirm you get a Titles heading above a Cast & Crew "
         "heading, and that real titles are in the first one.",
         "view:list"),
        ("Confirm both headings start OPEN, and that clicking one collapses "
         "just its own rows and leaves the other alone.", "view:list"),
        ("Check the channel count in the status area against the rows you can "
         "see. It should count the results, not the two headings.",
         "view:list"),
        ("With Group-by-type OFF, run a search, then clear the box. The list "
         "must come back FLAT — the search must not leave the checkbox "
         "ticked.", "view:list"),
        ("Turn Group-by-type ON, run a search, then clear it. Movies/Series/"
         "Live must come back, exactly as before the search.", "view:list"),
    ),
)
