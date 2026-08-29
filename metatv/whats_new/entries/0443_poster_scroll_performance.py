from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=443,
    version="0.55.0",
    date="2026-08-29",
    title="Scrolling into unloaded posters is no longer choppy",
    items=(
        "Scrolling a Discover shelf into an area whose posters had not loaded "
        "yet made the app stutter or stop responding. Scrolling back over "
        "posters that had already loaded felt fine.",
        "Every card waiting for a poster was being woken up every time ANY "
        "poster arrived, and all but one immediately did nothing. With a "
        "screen full of cards that is hundreds of thousands of wasted "
        "wake-ups per screenful.",
        "Each poster now goes only to the card that asked for it. Measured "
        "with 800 waiting cards: 157ms of pure overhead before, 2ms after.",
        "The app also now notices when its own interface stops responding and "
        "records it, so a future slowdown leaves evidence instead of needing "
        "to be reproduced.",
    ),
    test_steps=(
        "Open Discover and scroll quickly down through several shelves into "
        "posters that have not loaded, and confirm scrolling stays smooth.",
        "Scroll back up over the now-loaded posters and confirm it is still "
        "smooth.",
        "Confirm posters still appear, including on shelves showing the same "
        "title twice.",
        "Scroll rapidly and immediately switch views, confirming no crash from "
        "posters arriving after their card is gone.",
    ),
)
