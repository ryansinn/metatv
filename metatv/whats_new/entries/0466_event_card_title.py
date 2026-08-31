from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=466,
    version="0.60.0",
    date="2026-08-31",
    title="Event titles fit their cards",
    items=(
        "Long event names were drawn too large and cut through the middle of "
        "the letters — \"Manchester United v Ipswich Town Premier League "
        "Matchweek 2 2026/2027\" lost its first and last lines.",
        "The title was using the size meant for the heading at the top of a "
        "dialog box. It now has its own size, and its box is exactly two "
        "lines, so a title that is still too long is cut at a line break "
        "rather than through the text.",
        "Every card in the grid is now the same height regardless of title "
        "length, so the grid no longer looks ragged. Hover a card to see the "
        "full title.",
    ),
    test_steps=(
        ("Open Events with a long fixture name in view — no letters should be "
         "sliced top or bottom.", "view:events"),
        "Check the cards line up in even rows; short and long titles should "
        "produce identical card heights.",
        "Hover a card whose title is cut off and confirm the tooltip shows the "
        "whole thing.",
        "Switch between All / Pay-per-view / Live events and confirm the same "
        "holds in each scope.",
    ),
)
