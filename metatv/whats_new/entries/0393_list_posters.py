from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=393,
    version="0.50.0",
    date="2026-08-27",
    title="Posters show up in the channel list and in search results",
    items=(
        "Search for something and almost every row showed a letter tile "
        "instead of a poster. A search for 'castle' returned 2,467 results "
        "with 41 posters between them - and all 2,467 had a poster available.",
        "The list was reading only posters fetched by metadata enrichment, "
        "which covers about half a percent of a real library. The poster your "
        "source ships with each title was already stored and simply never "
        "looked at. That is 97% of your movies.",
        "Series had none stored at all: sources put a series poster in a "
        "different field from a movie poster, and only the movie one was ever "
        "read. All 82,525 series in a test library had an empty poster.",
        "On first launch you will see a short 'Restoring poster images' step "
        "that fills these in from data already on disk - about six seconds, no "
        "network, no source refresh needed.",
    ),
    test_steps=(
        "Type a common word into search - most rows should now show a poster "
        "rather than a letter tile.",
        "Search for a series by name and confirm series rows have posters too; "
        "this was the half that had nothing stored.",
        "Find a title that has been enriched with full metadata and confirm it "
        "still shows the better artwork - the source poster is a fallback, not "
        "a replacement.",
        "Scroll a long result list and confirm scrolling stays smooth; posters "
        "come from a column, not from re-reading each row's raw data.",
        "Check Discover and the Similar Titles strip still show their posters "
        "unchanged - they share the same resolver.",
        "Restart the app - 'Restoring poster images' must NOT run a second time.",
    ),
)
