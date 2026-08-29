from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=439,
    version="0.55.0",
    date="2026-08-29",
    title="101,441 titles get their release year back",
    items=(
        "Titles store a release date and a release year. The year was only "
        "ever filled in for content fetched since a fix earlier this year - "
        "437 titles out of 101,896 that had a date to derive it from.",
        "Everything else fell back to reading a year out of the channel name, "
        "which only works when the name happens to contain one. 60,448 titles "
        "ended up with no year at all despite having a perfectly good release "
        "date stored alongside.",
        "In 622 cases a year guessed from the filename disagreed with the "
        "actual release date, and the filename won.",
        "The year is now filled in from the release date for every title that "
        "has one. This runs once on the next launch.",
        "Titles whose release date is not a real date are left alone rather "
        "than being given a nonsense year.",
    ),
    test_steps=(
        "Launch the app and let the 'Recovering release years' step finish.",
        "Open a movie that previously showed no year and confirm a year now "
        "appears.",
        "Confirm titles whose name contains a year still show the right one.",
        "Relaunch and confirm the recovery step does not run a second time.",
    ),
)
