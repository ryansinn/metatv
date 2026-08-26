from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=360,
    version="0.41.0",
    date="2026-08-26",
    title="Fixed a crash when opening an upcoming EPG entry",
    items=(
        "Clicking an upcoming entry in Watch Alerts could take the whole app "
        "down. The EPG agenda's progress bar had a leftover line from the "
        "change that unified the progress bars, and it only ran when that view "
        "actually drew.",
        "The play marker in the sidebar's left column is now the normal icon "
        "size — it was rendering at about half the size it should have been.",
    ),
    test_steps=(
        "Click an upcoming entry under Watch Alerts → EPG → the agenda opens "
        "and the app stays up. This crashed before.",
        "Look at the agenda's progress bars → they draw normally and follow "
        "the current theme.",
        "Hover a live Watch Alerts row → the play triangle at the far left is "
        "clearly readable, the same size as other sidebar icons rather than a "
        "small mark.",
    ),
)
