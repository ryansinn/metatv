from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=782,
    version="0.218.0",
    date="2026-11-01",
    title="Similar titles, the trail map and Discover keep up with your changes",
    items=("Queue, favourite, like or mark something watched anywhere, and its badges update in "
           "the details pane's Similar and Other versions rows, the Similar Titles lightbox, the "
           "Explore trail map and the Discover shelves — without reopening them.",
           "Buttons on the trail map's rows now update the row badges too, not only the detail strip.",),
    test_steps=("Select a film whose details show Similar titles; right-click one of those titles "
                "in the main list → Add to Watch Later — its Similar row shows it queued.",
                "Open Similar Titles (lightbox), then favourite one of its strip titles from the main "
                "list — the strip card's star appears.",
                "Open Explore, mark a row's title watched from elsewhere — the row's ✓ badge appears.",
                "On Discover, queue a card's title from the main list — the card's Watch Later badge "
                "appears.",),
)
