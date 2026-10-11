from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=723,
    version="0.162.0",
    date="2026-10-10",
    title="Smoother launch and Recipe; person role toggle; channel headers stop where they should",
    items=("Launch no longer rebuilds the recommendation keyword index each time, and two "
           "background passes (genre fill, watch-alert scan) wait a minute instead of "
           "competing with the window as it opens.",
           "Recommendation scoring hands the screen a turn while it reads its candidates, "
           "so it no longer freezes the app for seconds.",
           "Clicking a tag in the Recipe overview redraws only that facet's tile.",
           "A person in your recipe has a role toggle: Any → Acting → Directing.",
           "A provider's '#### SECTION ####' header labels only its own groups and "
           "groups carrying its name — one used to run on over hundreds of unrelated "
           "groups. Takes effect on the source's next refresh."),
    test_steps=("Restart — the first minute scrolls and clicks without long stalls.",
                "Recipe → click several tags in the overview — no pause per click.",
                "Add a person from search — the pill shows 'Any'; click it — 'Acting', "
                "then 'Directing'; the matches change each time."),
)
