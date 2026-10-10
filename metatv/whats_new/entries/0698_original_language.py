from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=698,
    version="0.140.0",
    date="2026-10-09",
    title='Original language in Details',
    items=("Details shows a title's original language from TMDb, separate from the language of the copy you are looking at.",),
    test_steps=("Select a film whose metadata was fetched from TMDb after this update — Details shows 'Original language  English · TMDb'.",),
)
