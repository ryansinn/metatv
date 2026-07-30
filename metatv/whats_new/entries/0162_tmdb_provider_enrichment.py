from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=162,
    version="0.10.0",
    date="2026-07-30",
    title="More cross-language variants collapse automatically (provider TMDb lookup)",
    items=(
        "MetaTV now quietly asks your provider for the TMDb id of movies and "
        "series whose list entry didn't include one — so many more Spanish / "
        "English / 4K copies of the same title recognise each other and fold "
        "onto a single card over time, without you doing anything.",
        "It runs gently in the background, a small batch per launch, so it never "
        "slows the app down or hammers your provider — the catalogue keeps "
        "tidying itself across sessions.",
        "No API key or account is required — it uses your provider's own detail "
        "endpoint, the same one already used to read series episodes.",
        "You can turn it off any time with the tmdb_enrichment_enabled setting; "
        "already-collapsed cards and your favourites/ratings are never touched.",
    ),
    test_steps=(
        "Launch the app on a source with idless movies; wait ~15 s, then check "
        "the logs for a 'tmdb_enrich: pass complete — N id(s) found …' line "
        "(the background pass ran and reported hits/empties/deferred).",
        "Open Browse/Discover: a title that previously showed as separate "
        "language copies now shows ONE card with a '×N' badge once the pass has "
        "folded its variants (re-open the view or restart to see the refresh).",
        "Refresh that source (re-fetch its channels), relaunch, and confirm the "
        "pass runs again on its idless rows (the attempt marker reset on refresh) "
        "without re-processing rows that already have an id.",
        "Set tmdb_enrichment_enabled: false in config, relaunch, and confirm no "
        "'tmdb_enrich' pass line appears in the logs (the toggle disables it).",
    ),
)
