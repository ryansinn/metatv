from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=673,
    version="0.123.0",
    date="2026-09-11",
    title="New-episode alerts count only live sources, and open on one",
    items=(
        "A monitored series' \"+N eps\" used to count episodes that arrived "
        "on a source that has since been disabled or expired, and clicking "
        "the row opened that dead source's copy.",
        "The count now covers only sources you can play from, and the row "
        "opens the series on one of them.",
        "A series carried only by dead sources drops out of Alerts Matched "
        "and the \"N new\" count until one comes back.",
    ),
    test_steps=(
        "With a series monitored on two sources, disable one — the Watch "
        "Queue's \"+N eps\" drops to the live source's share and clicking it "
        "opens the live copy (details pane \"Source:\" names it).",
        "Disable both — the row and the pinned count disappear; re-enable "
        "one and they return.",
        "Mark seen — the count clears.",
    ),
)
