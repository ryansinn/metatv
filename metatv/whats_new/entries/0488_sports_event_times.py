from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=488,
    version="0.64.0",
    date="2026-09-01",
    title="Sports never showed anything as On Now",
    items=(
        "The Sports view's On Now and Upcoming lanes were always empty, even "
        "with games in progress, and every dated fixture turned up under "
        "Channels instead.",
        "Your source writes a game's window into the channel name — "
        "'MLB 04 | Mariners x Red Sox start:… stop:…'. That particular shape "
        "was the one form the app could not read, so those channels ended up "
        "with no start time at all. Without one, a fixture cannot be sorted "
        "into on-now, upcoming or finished, so it fell through to Channels.",
        "It is read now, and your existing channels are updated on the next "
        "launch — no source refresh needed.",
        "Separately, the lane buttons stopped showing which lane you were in: "
        "switching lanes left the old button looking selected as well. A "
        "button cleared by the app now repaints, so exactly one reads as "
        "active.",
    ),
    test_steps=(
        ("Open Sports, pick a sport with a game on now, and confirm On Now "
         "lists it rather than sitting empty.", "view:sports"),
        ("Click between On Now, Upcoming and Channels and confirm exactly one "
         "lane looks selected at a time.", "view:sports"),
        "Confirm dated fixtures appear under On Now / Upcoming / Finished "
        "according to their time, not all under Channels.",
    ),
)
