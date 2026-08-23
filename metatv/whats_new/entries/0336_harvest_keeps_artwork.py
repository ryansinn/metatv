from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=336,
    version="0.41.0",
    date="2026-08-23",
    title="Artwork is kept when a title's details are fetched",
    items=(
        "Many titles have no image in a source's bulk channel list — the only "
        "place their poster appears is the per-title details the app fetches "
        "separately. It was fetching those details, reading the genre, plot, "
        "cast and director out of them, and throwing the poster away.",
        "That was invisible until artwork went missing for another reason, at "
        "which point there was no way to get it back: 60 of 70 titles that "
        "lost a poster could not be repaired, purely because nothing in the "
        "app ever kept the image it had already downloaded.",
        "Poster and backdrop are now kept, and fill in wherever a title has "
        "none. An existing image is never replaced.",
        "The image is also no longer looked up two different ways in two "
        "different places, so the details fetch and the metadata plugin can't "
        "disagree about where a poster lives.",
    ),
    test_steps=(
        "Find a movie showing no poster in the details pane and note its name.",
        "Right-click it → Refresh metadata (or select it and let enrichment "
        "run) → the poster appears in both the details pane and the results "
        "row.",
        "Open a title that already has a good poster and refresh it → the "
        "poster does NOT change; existing artwork is never replaced.",
        "Browse a category of titles with no artwork for a minute, then "
        "revisit them → posters have filled in as their details were fetched.",
        "Check that plot, cast, director and genre still fill in as before on "
        "a title that was missing them.",
    ),
)
