from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=650,
    version="0.111.0",
    date="2026-09-08",
    title="Monitoring a series no longer waits on a network call it already had the answer for",
    items=(
        "Clicking \"Alert me about new episodes\" on a series you've already drilled "
        "into always made a live API call to establish the starting episode count, "
        "even when the episode count was already sitting in the local database from "
        "that drill-in. The fast path that was supposed to read it instead compared "
        "the wrong id (the app's own internal channel id) against a column that "
        "stores the provider's own series id, so it always came up empty and fell "
        "through to the slow, network-dependent path. Fixed to key the lookup the "
        "same way every other reader of that data does; setting a baseline for a "
        "series you've already opened is now instant and offline.",
    ),
    test_steps=(
        "Open a series' seasons/episodes (so they're cached locally), then click "
        "\"Alert me about new episodes\" from the channel menu or the details-pane "
        "monitor button — the baseline is set immediately, with no loading spinner "
        "or network wait.",
    ),
)
