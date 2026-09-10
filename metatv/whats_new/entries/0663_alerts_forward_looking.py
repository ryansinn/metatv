from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=663,
    version="0.119.0",
    date="2026-09-09",
    title="Watch-for alerts are forward-looking again, and deleting one clears its matches everywhere",
    items=(
        "A new watch-for rule no longer announces your whole existing library. "
        "The \"Watch for…\" dialog has always promised an alert when matching "
        "content \"appears on any of your sources\", and monitoring a series has "
        "always worked that way — but a keyword rule fired on everything "
        "already in the catalogue. One \"Evil Dead\" rule reported 102 titles "
        "(about eight actual films across languages and sources) the moment it "
        "was created.",
        "Creating a rule now takes what already matches as its starting point, "
        "recorded as already-seen, so the rule tells you about content that "
        "turns up from then on. The existing matches are still one click away — "
        "a rule's own \"View matches\" searches for its keyword any time.",
        "That also removes the freeze creating a rule used to cause: the old "
        "behaviour wrote the config file once per match and re-queried the "
        "database on the UI thread once per match, which locked the window for "
        "about 26 seconds on a large library. It is now a single write.",
        "Deleting a watch-for rule, or stopping alerts for a series, now clears "
        "its matches from the Watch Queue's \"Alerts Matched\" rows and count, "
        "the green markers in the channel list, and the details-pane Alert "
        "button. Previously only the Watch Alerts section itself updated, so "
        "the rule was gone while its matches stayed on screen.",
    ),
    test_steps=(
        "Add a watch-for rule for something you already own a lot of (e.g. a "
        "franchise). It should NOT flood you with notifications, and the rule "
        "should show nothing new.",
        "With that rule selected, use \"View matches\" — the existing content is "
        "still findable.",
        "Delete the rule (sidebar right-click → remove, and again via Watch "
        "Alerts → manage). The Watch Queue's \"Alerts Matched\" rows and its "
        "pinned \"N new\" line must clear immediately, without switching views.",
        "Right-click a series → stop alerting on new episodes: its row must "
        "disappear from the Watch Queue's matched-series group straight away.",
        "Refresh a source that genuinely gains a matching title and confirm the "
        "rule still fires for it.",
    ),
)
