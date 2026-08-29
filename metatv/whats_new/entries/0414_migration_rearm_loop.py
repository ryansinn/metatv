from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=414,
    version="0.53.0",
    date="2026-08-28",
    title='"Migration in progress" no longer appears at every launch',
    items=(
        "The offline metadata backfill announced itself at every start, ran, "
        "and finished having done nothing.",
        "It was offering itself one title it could never actually fill - a "
        "record with no name at all, which the filter accepted because it "
        "carried a rating of 0.",
        "Because the task decides whether it is needed by looking at the data "
        "rather than at a completion stamp, that one row re-armed it forever.",
        "The filter now asks for the same thing the task requires: a usable "
        "title. Nothing is offered that cannot be done.",
    ),
    test_steps=(
        "Start the app twice in a row. The 'migration in progress' notice "
        "should not appear on either start, once any real backfill has "
        "finished.",
        "Add a new source and let it ingest. The backfill should still run "
        "for the new titles and then stop announcing itself.",
        "Open a movie or series that was filled by the backfill and confirm "
        "its plot, cast and genre are still shown.",
    ),
)
