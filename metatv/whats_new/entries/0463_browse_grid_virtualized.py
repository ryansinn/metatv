from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=463,
    version="0.60.0",
    date="2026-08-31",
    title="Browsing a big result set no longer eats the machine",
    items=(
        "The card grid behind Discover's \"See all\" and a recipe's \"Show "
        "all\" built a real widget for every result and never threw one away "
        "— so scrolling a large recipe kept growing until the app was using "
        "gigabytes.",
        "It now draws only the cards on screen. Loading 20,000 results went "
        "from 5.2 seconds and 1.6 GB to 0.1 seconds and 23 MB, and the number "
        "of live cards stays around 50 no matter how far you scroll.",
        "The scrollbar is now honest from the first frame: it spans the whole "
        "result set instead of growing as you scroll into it.",
        "Recipes with a broad ingredient were the worst case — 115,377 of "
        "your movie titles are distinct, so one wide genre could page in "
        "thousands of cards.",
    ),
    test_steps=(
        ("Open Discover and click \"See all\" on a shelf. The grid should "
         "appear instantly and scroll smoothly.", "view:discover"),
        ("Open Recipe, build one with a broad ingredient (a whole genre), "
         "and click \"Show all\". Scroll a long way down — it should stay "
         "responsive and memory should stay flat.", "view:recipe"),
        "Scroll to the very bottom, then back to the top. The first cards "
        "should look exactly as they did, posters included.",
        "Resize the window while a grid is open; cards should re-flow into "
        "the new column count without gaps or overlaps.",
        "Type in the browse filter box and confirm results narrow correctly.",
        "Switch to the list view and back to the grid; both should show the "
        "same items.",
    ),
)
