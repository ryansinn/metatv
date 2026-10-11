from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=724,
    version="0.163.0",
    date="2026-10-11",
    title="Recommendations no longer freeze the app while they score",
    items=("Scoring recommendations reads tens of thousands of titles in the background; "
           "it now hands the screen a turn as it goes, instead of freezing the app for "
           "seconds.",),
    test_steps=("Open Discover or Recipe right after launch — scrolling and clicking stay "
                "responsive while recommendations load.",),
)
