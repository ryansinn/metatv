from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=518,
    version="0.69.0",
    date="2026-09-02",
    title="Empty sidebar sections stop reserving space they cannot use",
    items=(
        "Recordings and Downloads no longer open as tall empty panels. A "
        "section with nothing in it is now just its header, so the space goes "
        "to the sections that have something to show.",
        "The cause was a measurement, not a layout choice: an empty list "
        "reports the size a list would USUALLY be rather than zero, and the "
        "sidebar was sizing itself against that guess. Every section is "
        "affected, not only these two.",
    ),
    test_steps=(
        ("With no recordings and no downloads, look at the sidebar: the "
         "Recordings and Downloads sections should be header-height, the same "
         "as any other collapsed row, not tall blank panels.",
         "view:list"),
        ("Confirm each still shows its count and its folder button in the "
         "header, and still opens and closes when you click it.",
         "view:list"),
        ("Check a section that DOES have content — Watch Queue or "
         "Recommended — still shows its rows and can still be dragged taller.",
         "view:list"),
    ),
)
