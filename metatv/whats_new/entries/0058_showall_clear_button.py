from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=58,
    version="0.8.0",
    date="2026-06-24",
    title="Clear button for Show-All filter box",
    items=(
        "Added a × clear button next to the Filter box in the Recipe 'Show all' browse view.",
    ),
    test_steps=(
        "Open the Recipe chip → click 'Show all' on any shelf → type text in the Filter box → the card list narrows.",
        "Click the × button to the right of the filter box → the filter clears and the full result set returns.",
    ),
)
