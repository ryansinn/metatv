from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=246,
    version="0.23.0",
    date="2026-08-03",
    title="TMDb + OMDb metadata providers",
    items=(
        "Two new metadata sources — TMDb and OMDb — can now fill in poster, "
        "plot, cast, director, genres, and ratings for movies/series whenever "
        "your provider's own data is thin. Add an API key in Settings → "
        "Metadata & API Keys to turn either on; a title already linked to a "
        "TMDb id skips searching and fetches it directly.",
        "Settings → Metadata & API Keys now has a 'Test' button beside each "
        "API key field — it checks the key against the live service (off the "
        "UI thread) and shows a clear connected/failed result inline, before "
        "you save.",
        "The 'Enable metadata enrichment' and 'Auto-fetch on channel select' "
        "switches in Settings now actually take effect: turning enrichment "
        "off stops every metadata source (including the built-in provider "
        "data), and turning auto-fetch off stops the background lookup that "
        "runs when you click a channel (a manual refresh is unaffected).",
    ),
    test_steps=(
        "Settings → Metadata & API Keys: paste any text into the TMDb API "
        "key field and click 'Test' → the button disables briefly then shows "
        "a red '✗ Invalid API key' (or a network-error message) inline; do "
        "the same for OMDb.",
        "Leave both API key fields empty and click each 'Test' button → each "
        "shows '✗ Enter an API key first' without contacting the network.",
        "Turn off 'Enable metadata enrichment', click OK, then select a movie "
        "or series channel → the details pane shows only the basic channel "
        "info (no plot/cast fetch fires); turn it back on and re-select the "
        "same channel → metadata loads normally.",
        "Turn off 'Auto-fetch on channel select', click OK, then click "
        "through several movie/series channels → the details pane never "
        "shows a metadata-loading flicker for any of them.",
    ),
)
