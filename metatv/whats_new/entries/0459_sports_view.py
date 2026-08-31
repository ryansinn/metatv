from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=459,
    version="0.58.0",
    date="2026-08-30",
    title="A Sports view, filtered by sport and league",
    items=(
        "New chip in the view switcher. It lists your sports channels with two "
        "dropdowns above them — pick a sport, and the league list narrows to "
        "the leagues that sport actually has. Each row shows the team where "
        "one was identified, with the league, sport and quality beside it.",
        "The filter bar and the queries behind it had been finished and "
        "unused for a long time. What was missing was not the screen: those "
        "queries showed every channel from every source, including 16,715 "
        "sports channels belonging to a source you had switched off. Opening "
        "the view would have shown you half a library you had disabled.",
        "That is fixed, and the fix reaches the dropdowns too — a sport whose "
        "channels are all excluded no longer appears in the list offering "
        "them.",
        "Rows are the same row component used by History, Favourites and the "
        "Watch Queue, so they will keep matching those as the design moves.",
    ),
    test_steps=(
        ("Click the Sports chip in the view switcher. A list of sports "
         "channels should appear with Sport and League dropdowns above it.",
         "view:browse"),
        "Pick a sport — Hockey, say. The League dropdown should now offer only "
        "that sport's leagues, and the list should narrow.",
        "Pick a league. The count under the filters should match the number of "
        "rows shown.",
        "Confirm no channel from a disabled source appears. Turn a source off "
        "in Sources, come back, and its channels should be gone from both the "
        "list AND the dropdowns.",
        "Double-click a row — it should play. Single-click should show it in "
        "the details pane. Right-click should open the channel menu.",
        "Switch to another view and back. The list should reload without "
        "leaving the previous view's results behind.",
    ),
)
