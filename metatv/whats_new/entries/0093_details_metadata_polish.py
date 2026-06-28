from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=93,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane: genres wrap, and empty Overview / Cast sections disappear",
    items=(
        "Genre chips now wrap onto multiple lines within the details panel instead "
        "of overflowing its width. Titles whose source lists every genre as one "
        "comma-separated string (e.g. \"Cowboy Bebop\") are now split into one chip "
        "per genre so they wrap cleanly — no genres are removed.",
        "The Overview section now hides entirely when a title has no description, "
        "instead of showing an empty 'Overview' box.",
        "The Cast & Crew section now hides entirely when a title has no cast or crew, "
        "instead of showing an empty box.",
        "Both sections reappear automatically when you select another title that does "
        "have a description or cast.",
    ),
    test_steps=(
        "Open a movie/series with many genres (e.g. \"Cowboy Bebop\"). Confirm the "
        "genre chips wrap onto multiple rows and stay inside the details panel — the "
        "panel is NOT forced wider and no chip is cut off.",
        "Confirm every genre is still present as its own chip (none dropped), and a "
        "compound genre like \"Sci-Fi & Fantasy\" stays a single chip.",
        "Open a title that has NO plot/description. Confirm there is no empty "
        "'Overview' heading or blank box — the whole section is gone.",
        "Open a title that has NO cast or director. Confirm there is no empty "
        "'Cast & Crew' box.",
        "Now select a different title that DOES have a description and cast. Confirm "
        "the Overview and Cast & Crew sections reappear with their content (proving "
        "they reset correctly when the pane is reused).",
    ),
    addresses=("flagged:e87956eb-7dab-430e-a2f3-1459be991270",),
)
