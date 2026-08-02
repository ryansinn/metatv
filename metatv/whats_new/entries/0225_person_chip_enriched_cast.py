from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=225,
    version="0.19.0",
    date="2026-08-01",
    title="Cast/Crew chip now finds movies too",
    items=(
        "The details-pane Cast/Crew filter chip (e.g. 'Cast/Crew: Carl Weathers') "
        "now matches the same enriched cast/director data shown in the details "
        "pane, not just the raw provider feed — movies whose cast only came from "
        "enrichment now show up, not just series.",
        "The Genre chip was aligned the same way: it now matches the ingestion-"
        "computed genre list, so aliased/canonicalised genres match correctly.",
    ),
    test_steps=(
        "Open a movie whose cast came from enrichment (not the raw provider feed) "
        "→ click an actor's name in Cast/Crew → the movie itself now appears in "
        "the filtered results (previously only series with raw-feed cast showed).",
        "Click a Genre chip in the details pane → results still include titles "
        "matching that genre.",
    ),
)
