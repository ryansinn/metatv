from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=379,
    version="0.41.0",
    date="2026-08-26",
    title="Open a programme by clicking it, or just play it",
    items=(
        "A programme showing on several channels now opens when you click "
        "anywhere on the row - the title, the time, the empty space. Before, "
        "only the small arrow at the far left responded.",
        "That arrow is now a stacked-boxes marker instead of a chevron. A "
        "chevron at this size looked almost exactly like the play triangle "
        "sitting next to it; the new marker says \"a list of sources\", which "
        "is what opening the row shows you. It fills in when the row is open.",
        "Hovering the row puts a play button in the same column the "
        "individual sources use, so you can play the first available source "
        "without opening the row first. The play buttons now line up in one "
        "column down the whole group.",
        "Upcoming programmes still offer no play button - there is nothing to "
        "play yet.",
        "Watch Alerts rows and group headings are tighter: the padding around "
        "each row is halved, so the section fits noticeably more without "
        "anything being cut off.",
    ),
    test_steps=(
        "In Watch Alerts, find an EPG programme showing on several channels - "
        "it has a stacked-boxes marker at its far left. Click the TITLE: the "
        "row opens and lists the channels.",
        "Click the title again - it closes. Click the marker itself - it "
        "opens. Click the empty space right of the time - it opens.",
        "With the row open, the marker is filled in rather than outlined.",
        "Hover the programme row - a blue play triangle appears just right of "
        "the marker, in the SAME column as the play buttons on the channel "
        "rows below it. Click it: playback starts on the first source, with "
        "no need to open the row.",
        "Check the alignment: the programme's title starts at the same left "
        "edge as its channels' names, and every play button in the group sits "
        "in one vertical line.",
        "Hover an UPCOMING programme (one that has not started) - no play "
        "button appears, and clicking the row opens it instead.",
        "Compare the section's density to before: rows and the MOVIES / "
        "SERIES / EPG headings are tighter, and no letter is clipped - check "
        "a title with a descender like \"Stargate SG-1\".",
    ),
)
