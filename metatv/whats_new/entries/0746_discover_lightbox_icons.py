from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=746,
    version="0.183.0",
    date="2026-10-19",
    title="Discover, Explore and the preview: the same clean icons",
    items=("Discover cards and shelves, the Browse list, the poster preview (lightbox), "
           "Explore and the Similar rows use the app's one icon set. Icons now always take "
           "the colour of the words beside them, including on the preview's dark panel in "
           "the light theme.",),
    test_steps=("Open Discover — a card's corner badges (liked, favourite, Watch Later, watched) "
                "are line icons, not emoji; its rating badge leads with a star icon.",
                "Click a poster to open the preview — Watch Later, Favorite, Hide and Explore show "
                "line icons in the same colour as their words; switch to the Daylight theme and "
                "they stay visible.",
                "Open Explore from History — the header shows a history icon before the title."),
)
