from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=647,
    version="0.110.0",
    date="2026-09-08",
    title="TMDb ids and series runtimes reach the details pane",
    items=(
        "Every movie and series metadata row was missing its TMDb id — the code read "
        "a raw-payload key ('tmdb_id') the provider has never sent; both movie and "
        "series catalog entries ship the id under 'tmdb' instead. Fixed at the shared "
        "resolver both ingestion and the one-time backfill call, so no two answers to "
        "'what tmdb id does this row have' can drift apart again. A one-time pass now "
        "also fills the id on the roughly 650,000 metadata rows written before this fix.",
        "The offline metadata backfill (the pass that builds a details-pane baseline "
        "for a title straight from the provider's own catalog data, with no network "
        "call) already computed a series' runtime and a title's TMDb id but never "
        "applied either to the row it created — only a later, separate one-time pass "
        "did, so a title picked up after that pass ran would silently miss both "
        "forever. Both are now filled at the same point the row is created.",
    ),
    test_steps=(
        "Open the details pane for a movie or series whose source ships a TMDb id "
        "(most VOD content) — a TMDb id-dependent feature (e.g. the 'Other Versions' "
        "grouping or a TMDb-sourced chip) now recognizes it instead of treating the "
        "title as id-less.",
        "Open a series' details pane — its runtime now shows when the provider's "
        "catalog data carries an episode duration, instead of being blank.",
        "Refresh a source and immediately open a newly-added series before any "
        "background enrichment runs — its runtime and TMDb id (when the provider "
        "sends one) are already populated from the initial catalog sync.",
    ),
)
