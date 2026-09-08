from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=628,
    version="0.103.0",
    date="2026-09-07",
    title="Keyboard shortcuts — and a cheat-sheet that lists every one of them",
    items=(
        "Ctrl+F (Cmd+F on macOS) or / jumps to the search box with whatever "
        "was in it selected, so the next thing you type replaces it.",
        "Ctrl+1 to Ctrl+5 switch views, in the switcher's own left-to-right "
        "order: Search, EPG, Recommended, Discover, Recipe.",
        "Space plays and pauses what is playing; Ctrl+. stops it. Ctrl+Down "
        "and Ctrl+Up walk the channel list without starting anything.",
        "Ctrl+B and Ctrl+D show or hide the sidebar and the details pane — "
        "the same toggles the Layout menu has always had.",
        "Escape clears the search box and drops out of it, or closes the "
        "preview overlay, the enlarged poster or the Explore map when one of "
        "those is in front.",
        "None of the plain-character keys fire while you are typing: /, ? and "
        "Space go into a search or filter box as characters. Ctrl+F and F1 "
        "still work from inside one.",
        "Press ? or F1 — or open Tools ▸ Keyboard Shortcuts… — for the whole "
        "list. Every shortcut also appears in a menu, and the control it "
        "drives says its key in its tooltip.",
    ),
    test_steps=(
        "With the app on Search, click somewhere in the channel list and "
        "press / — the caret lands in the header search box.",
        "Type a title, then press Ctrl+F — the whole query is selected, so "
        "typing again replaces it rather than appending.",
        "With the caret still in the search box, type a / and a space — both "
        "appear in the box, nothing is played or paused, and no cheat-sheet "
        "opens.",
        "Press Escape in the search box — it empties and the caret leaves it; "
        "the full channel list comes back.",
        "Press Ctrl+1 through Ctrl+5 in turn — the view changes to Search, "
        "EPG, Recommended, Discover and Recipe, and the chip that lights up "
        "each time is the one in that position in the switcher.",
        "Play something, then press Space — it pauses; press Space again — it "
        "resumes. Press Ctrl+. — playback stops.",
        "Press Space with nothing playing — the status bar says \"Nothing is "
        "playing\" rather than doing nothing silently.",
        "Back on Search, click a channel row, then press Ctrl+Down and "
        "Ctrl+Up — the selection moves a row at a time and the details pane "
        "follows it; nothing starts playing.",
        "Turn on \"Group by type\" and hold Ctrl+Down through a section "
        "heading — the selection steps over the heading onto the next real "
        "channel.",
        "Press Ctrl+B, then Ctrl+D — the sidebar and then the details pane "
        "collapse; press each again and they come back at the width they had.",
        "Open a movie's details and click a Similar title to open the preview "
        "overlay, then press Escape — the overlay closes and you are back "
        "where you were.",
        "Press ? (and then F1) — the Keyboard Shortcuts sheet opens, listing "
        "every key above in two columns, and closes on Close or Escape.",
        "Open Tools — \"Keyboard Shortcuts…\" is in the menu; check the View "
        "and Playback menus, which now name each view and each playback "
        "action with its key beside it.",
        "Hover the search box and the EPG chip — each tooltip ends with its "
        "key, e.g. \"(Ctrl+F or /)\" and \"(Ctrl+2)\".",
        "Put the caret in the search box and press F1 — the cheat-sheet still "
        "opens and no \"?\" is typed into the box.",
    ),
)
