from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=332,
    version="0.41.0",
    date="2026-08-23",
    title="Pinned channels in EPG → My Channels actually do something",
    items=(
        "A pinned channel card did nothing when you clicked it and offered no "
        "right-click menu, so if the guide had no data for that channel the "
        "card was a name and an ✕ and nothing more.",
        "Clicking a pinned channel now opens it in the details pane, and "
        "right-clicking gives the same channel menu you get in On Now — play, "
        "favourite, queue, hide, stop watching, and the rest.",
        "The Play button no longer waits for guide data. It used to appear "
        "only when the EPG knew what was currently on, which tied whether a "
        "channel could be played to whether it had been matched to a guide — "
        "two unrelated things.",
    ),
    test_steps=(
        "Open EPG → On Now, right-click any channel → 'Watch this channel'.",
        "Switch to EPG → My Channels → the pinned card shows a ▶ Play button "
        "whether or not it says 'No EPG data' underneath.",
        "Click the card body (not a button) → the details pane on the right "
        "switches to that channel.",
        "Right-click the card → the channel menu opens, with the same actions "
        "as right-clicking in On Now.",
        "Click ▶ Play on a card that says 'No EPG data' → the channel plays.",
        "Click ✕ → the channel is unpinned and the card disappears.",
        "Go back to On Now and right-click a channel there → its menu is "
        "unchanged, and still offers Track show / Assign category / Hide show.",
    ),
)
