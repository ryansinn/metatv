from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=646,
    version="0.109.0",
    date="2026-09-08",
    title="Series show up in Recently Added, and more titles get a year and a genre",
    items=(
        "Series never appeared in the Discover 'Recently Added' shelf — the provider "
        "sends series their own 'last modified' timestamp instead of the 'added' date "
        "movies and live channels carry, and ingestion only ever read the latter. Every "
        "one of 127,679 series had no recorded add date, so the shelf's top-150 ordering "
        "structurally could never contain one. Fixed at ingestion.",
        "A movie or series whose name has a year followed by an unrecognised bracketed "
        "tag — e.g. '(2022) (MULTI FHD HEVC)' or '(2022) (PORTUGUESE ENG-SUB)' — used to "
        "lose its year entirely, with no year cell, no decade filter, and a year-less "
        "identity that could wrongly merge with an unrelated title of the same name. "
        "Measured about 8,500 real titles newly keep their year, with no change to "
        "titles that already worked.",
        "Series with no year in their name but a year from enrichment (about 63,000 of "
        "them) now show that year too, instead of staying blank.",
        "A movie's genre, when guessed from its provider category, is now recognised "
        "whatever case the category uses (an uppercase 'ANIME' category used to be "
        "silently dropped while a lowercase one worked) — plus several missing genre "
        "aliases (Documentales, Stand-Up Comedy, and localized Sci-Fi & Fantasy forms). "
        "Measured about 12,300 movies newly show a genre.",
        "Playing a channel now builds its stream address fresh from the source's current "
        "best-reachable host and saved login at the moment you press Play, instead of "
        "trusting an address saved the last time the library refreshed — which could go "
        "stale if a source changed its password or dropped a dead server in between.",
    ),
    test_steps=(
        "Refresh a source with series content, open Discover's 'Recently Added' shelf — "
        "series titles now appear alongside movies, not just movies.",
        "Find a title whose year previously showed blank in the channel list/details pane "
        "(a name like 'Movie (2022) (MULTI FHD HEVC)') — after a library refresh it now "
        "shows its year and sorts correctly under its decade filter.",
        "Open the Genres filter/shelf for a source with uppercase provider categories "
        "(e.g. 'ANIME') — after a refresh, titles under that category now carry the "
        "matching genre chip.",
        "Play a live channel or movie normally — playback starts as before with no "
        "visible change in behavior.",
    ),
)
