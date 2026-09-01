from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=506,
    version="0.65.0",
    date="2026-09-01",
    title="The Recordings section was always empty",
    items=(
        "The sidebar's Recordings list asked the database for your recordings "
        "using a field name that does not exist, so the request failed every "
        "time — once a second, quietly, behind an error the app caught and "
        "logged rather than showed. Recordings were being scheduled and run "
        "correctly the whole time; you just could not see any of them.",
        "The list now loads, and it is ordered by when each recording actually "
        "starts — including the couple of minutes early it begins — rather "
        "than by the time printed in the guide.",
    ),
    test_steps=(
        ("Schedule a recording, then confirm it appears in the sidebar's "
         "Recordings section."),
        "Confirm the time shown beside it is the recording's own start time.",
        ("Schedule a second recording that starts later and confirm the list "
         "puts the later one first."),
        ("Cancel one of them and confirm it leaves the section rather than "
         "lingering."),
        ("Check the log for 'could not refresh the Recordings section' and "
         "confirm it no longer appears."),
    ),
)
