from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=461,
    version="0.59.0",
    date="2026-08-30",
    title="The Sports view no longer freezes the app",
    items=(
        "Opening Sports locked the window for minutes. It was building a real "
        "widget for every single channel before it could show anything — "
        "9,769 of them under a filter, 28,018 with the filters open.",
        "It now uses the same virtualized list the Search results use, which "
        "draws only the rows on screen. Loading 28,018 rows went from about "
        "11 seconds of frozen window (measured, and far worse on a real "
        "display) to 3 milliseconds.",
        "Sports rows are now ordinary channel rows, so they finally show what "
        "every other list shows: poster thumbnails, your like/dislike, watch "
        "progress, the \"other versions\" count, genres and the region badge. "
        "The old Sports row could not carry any of those.",
        "Sport and league still show, and the sport now reads \"American "
        "Football\" rather than the stored \"American_Football\".",
        "Titles come from the same field every other view uses. A few sports "
        "rows used to take their title from a separate field that kept the "
        "provider's prefix — \"4K| V SPORT+ UHD\" showed as \"4K| vs SPORT+ "
        "UHD\" and now reads \"V SPORT+\".",
        "Hover a sports row to see the provider's original channel name, "
        "which the cleaned title replaces.",
    ),
    test_steps=(
        ("Click the Sports chip with Sport and League both set to All. The "
         "list should appear immediately — no beachball, no frozen window.",
         "view:browse"),
        "Scroll the full list fast, top to bottom. It should stay smooth.",
        "Check a row shows the sport and league beside the title, and that a "
        "sport reads as \"American Football\", not \"American_Football\".",
        "Confirm sports rows now look like Search rows — poster, quality, "
        "region badge, and a watch-progress bar on anything you have started.",
        "Hover a row and confirm the tooltip shows the provider's raw channel "
        "name.",
        "Right-click a row for the context menu, middle-click one to open it "
        "in the other pane, and double-click one to play it.",
        "Narrow to a single sport and league, then widen back to All; the "
        "count above the list should track what is shown.",
        "Turn a source off in Sources and confirm its sports channels vanish.",
    ),
)
