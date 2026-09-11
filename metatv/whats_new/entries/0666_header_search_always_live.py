from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=666,
    version="0.120.0",
    date="2026-09-11",
    title="The header search box is always live",
    items=(
        "The header search box is now typeable from every view, not just "
        "Search — including a series' episode list, which used to grey it "
        "out and then, because nothing re-enabled it on any other view "
        "switch, leave it disabled everywhere until you went back to the "
        "channel list.",
        "Pressing Enter anywhere jumps to Search and runs whatever is in "
        "the box, so the box is now a way INTO Search, not just a filter "
        "you could only reach once already there.",
        "Clicking into the box now selects the previous query, the same "
        "way the keyboard shortcut already did, so you can click once and "
        "start typing a clean search instead of editing into the middle "
        "of the old one.",
    ),
    test_steps=(
        "Open a series (so the episode list shows), then click Discover — "
        "the header search box should still accept typing.",
        "From the EPG view, type a title into the header search box and "
        "press Enter — Search should open with results for it.",
        "With a previous query already in the header search box, click it "
        "once and start typing — the old text should be replaced, not "
        "appended to.",
    ),
)
