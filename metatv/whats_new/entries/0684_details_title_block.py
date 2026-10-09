from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=684,
    version="0.131.0",
    date="2026-10-08",
    title="A cleaner top to the details pane",
    items=(
        "Genres sit right under the title, the rating is just the number out "
        "of 10, TMDb/IMDb chips copy their id on click, and the source with "
        "this copy's collection is one row of clickable chips.",
    ),
    test_steps=(
        "Select a film with metadata — genres appear as chips right under "
        "'Movie · year'; no stars beside the rating.",
        "Click the TMDb chip — its id is on the clipboard and the status bar "
        "says so.",
        "Click the source chip — the list shows that source; click the "
        "collection chip — the list filters to that collection.",
    ),
)
