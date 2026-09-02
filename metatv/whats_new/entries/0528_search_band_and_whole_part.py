from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=528,
    version="0.71.0",
    date="2026-09-02",
    title="Search section headers, and a Whole/Part switch on each one",
    items=(
        "The Titles and Cast & Crew headers are now the band they were "
        "designed as: the section name at the left, a hairline running across "
        "to the count, and the caret at the far right. The blank stretch to "
        "the right of the header is gone — that gap was the missing rule.",
        "Each section carries a Whole | Part switch. Part is the default and "
        "shows everything, exactly as before. Whole narrows that section to "
        "results where what you typed is a word in its own right — so "
        "searching \"Tron\" can drop Astronaut and Strongman without touching "
        "the other section.",
        "It is per section, so you can tighten a cluttered Titles list while "
        "leaving Cast & Crew wide open, and nothing is ever hidden until you "
        "ask for it.",
    ),
    test_steps=(
        ("Search anything. Each section header should be a band: name at the "
         "left, a thin line across to the number, then the switch and the "
         "caret at the right edge — no empty stretch.", "view:list"),
        ("Search \"Tron\" and click Whole on Titles. Astronaut and Strongman "
         "should go; Tron and Tron: Legacy should stay.", "view:list"),
        ("Confirm the Cast & Crew section is unaffected by that click, and "
         "still says Part.", "view:list"),
        ("Click Part again and confirm every result comes back.", "view:list"),
        ("Check the count in the header follows what is on screen when you "
         "switch to Whole.", "view:list"),
        ("Turn off search and confirm Movies/Series/Live headers carry NO "
         "switch — there is no word-match to narrow when nothing was typed.",
         "view:list"),
    ),
)
