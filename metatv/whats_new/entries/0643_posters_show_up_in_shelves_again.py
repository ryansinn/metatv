from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=643,
    version="0.107.0",
    date="2026-09-08",
    title="Posters show up in shelves again",
    items=(
        "A Discover card whose poster was already in memory never received it, so the card "
        "kept its placeholder icon — most visibly for a title you had just opened in the "
        "details pane, because opening it there is what put the poster in memory.",
        "Those stuck cards also kept an endless shimmer animation running, which is why a "
        "shelf full of placeholders made the whole window feel heavy.",
    ),
    test_steps=(
        "Open Discover and click a title so its poster loads in the details pane, then scroll "
        "that shelf away and back — the card shows the poster instead of a placeholder icon.",
        "Scroll a shelf down past several rows and back up — previously loaded posters are "
        "still shown, and no card is left shimmering.",
    ),
)
