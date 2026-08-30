from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=457,
    version="0.58.0",
    date="2026-08-30",
    title="Watch the trailer before you commit",
    items=(
        "A Trailer button now sits under Play in the details pane, on every "
        "title whose provider sent one. That is 114,308 of your channels.",
        "Left-click plays it in the player, in its own window, so whatever you "
        "were already watching keeps going. Right-click offers \"Play trailer\" "
        "and \"Play trailer on YouTube\" — the second is there for when the "
        "player's YouTube support goes stale, or you want the page itself.",
        "The link was in your library the whole time. The app looked for it "
        "under one name and your providers send it under another, so 68,160 "
        "trailers were invisible — and even the 46,148 it did find were stored "
        "and never shown anywhere.",
        "There is no pop-up video window inside the app: it cannot embed a web "
        "player, so a trailer plays through the same player as everything else "
        "and inherits its buffering, its window handling and its controls.",
        "Existing titles get their trailer filled in by a startup pass on the "
        "next launch; anything refreshed after that picks it up as it arrives.",
    ),
    test_steps=(
        ("Launch MetaTV and let the startup step \"Reading details the "
         "provider already sent\" finish.", "view:browse"),
        ("Open a popular movie in the details pane. A \"Trailer ▶\" button "
         "should sit at the left of the row under Play, before Watch Later.",
         "sample:vod"),
        "Click it. The trailer should open in a player window, and anything "
        "you already had playing should keep playing.",
        "Right-click the Trailer button. Two entries: \"Play trailer\" and "
        "\"Play trailer on YouTube\". The second should open your browser.",
        "Open a title with no trailer — the button must be absent entirely, "
        "not present-and-dead.",
        "Open a title WITH a trailer, then one WITHOUT. The button must "
        "disappear; it must never play the previous title's trailer.",
        ("Open a live channel. The Trailer button should not appear there.",
         "sample:live"),
    ),
)
