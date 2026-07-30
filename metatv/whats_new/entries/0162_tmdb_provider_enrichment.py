from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=162,
    version="0.10.0",
    date="2026-07-30",
    title="More cross-language variants collapse automatically (on-demand TMDb lookup)",
    items=(
        "MetaTV now recognises many more Spanish / English / 4K copies of the same "
        "movie or series as one title and folds them onto a single card. It works "
        "in three ways, cheapest first: it copies a TMDb id from a sibling copy that "
        "already has one (instant, no network), and — only for the titles you're "
        "actually looking at — quietly asks your provider for the id of the rest.",
        "It's on-demand, not a startup crawl: as you browse Discover, Recipes, the "
        "channel list, or a title's Other Versions, the titles on screen get matched "
        "in the background. A small 'Updating N titles from {source}…' note appears "
        "while it works and clears when done — that's also why a shelf may gently "
        "re-settle as copies merge.",
        "New Tools → Missing TMDb Data view: see how many titles still lack a TMDb id, "
        "broken down by source, plus a summary of how many were matched by each method "
        "and how many only a future TMDb-API lookup could resolve. Opening it also "
        "nudges those titles to be matched.",
        "No API key or account is required — it uses your provider's own detail "
        "endpoint. Matched ids survive a source refresh now, and your "
        "favourites/ratings are never touched. Turn it off any time with the "
        "tmdb_enrichment_enabled setting.",
    ),
    test_steps=(
        "On a source with idless movies, open Browse/Discover: within a few seconds a "
        "'Updating N titles from {source}…' toast appears while the on-screen titles "
        "are matched, then clears — confirm a title that showed as separate language "
        "copies folds into ONE card with a '×N' badge (re-open the view to see it).",
        "Open a movie's details and check 'Other Versions'; confirm the same "
        "background match toast can appear and idless sibling copies collapse in.",
        "Open Tools → Missing TMDb Data: confirm it lists idless titles grouped by "
        "source with counts and an 'identified X% … K titles remain that only the TMDb "
        "API could resolve' summary, and that the counts shrink as matching runs.",
        "Refresh that source and relaunch: confirm titles that already gained an id "
        "keep it (they are not wiped or re-fetched), while still-idless rows are tried "
        "again as you browse.",
        "Set tmdb_enrichment_enabled: false in config, relaunch, browse, and confirm "
        "no 'Updating … titles' toast appears and no 'tmdb_enrich' lines log.",
    ),
)
