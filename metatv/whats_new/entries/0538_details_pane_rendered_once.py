from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=538,
    version="0.78.0",
    date="2026-09-02",
    title="Clicking a channel builds its details panel once instead of twice",
    items=(
        "Every click on a channel rendered the details panel twice and looked "
        "its metadata up twice — two database reads and two background threads "
        "for one channel, on every selection.",
        "Two handlers both answered the same click: the one for the selection "
        "moving, and the one for the click itself. They now agree, by asking "
        "what the panel is already showing.",
        "Clicking a row whose details are already open still refreshes it when "
        "the panel has drifted elsewhere — for example after a detour through "
        "Discover — and closing the player still brings back Resume.",
    ),
    test_steps=(
        ("Click a channel in the list. Its details must appear as before, with "
         "no flicker or double-load.", "view:list"),
        ("Arrow up and down the list quickly and confirm details keep up and "
         "show the right channel.", "view:list"),
        ("Select a channel, go to Discover and click a different title, then "
         "return and click the still-selected row — its details must come "
         "back.", "view:list"),
        ("Play something part-way, close the player, and confirm the details "
         "panel offers Resume.", "view:list"),
    ),
)
