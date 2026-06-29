from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=105,
    version="0.9.0",
    date="2026-06-28",
    title="Playback-state indicator in the channel-list row separator",
    items=(
        "The little '·' between a row's leading icons/tags and its title is now a "
        "single 3-state playback indicator, so you can tell at a glance which titles "
        "you've started: a plain '·' = not started, an orange ▶ = in progress / "
        "resumable (same orange as the details Resume button), and a green ✓ = "
        "watched.",
        "The watched checkmark that used to float, misaligned, in the far-left margin "
        "has moved into this single fixed slot — rows no longer shift and there's only "
        "one indicator per row.",
        "Colourblind-safe by design: the SHAPE (dot vs play-triangle vs check) carries "
        "the meaning; colour is only reinforcement. Watched rows stay dimmed as before.",
    ),
    test_steps=(
        "Partially watch a movie, then find it in the channel list / search results: "
        "its row shows an orange ▶ where the '·' separator used to be (between the "
        "[REGION]/tags and the title).",
        "Finish that movie (or right-click → Mark as Watched): the same row's indicator "
        "becomes a green ✓ in the SAME spot, and there is NO second checkmark floating "
        "in the far-left margin.",
        "Find an untouched title: its row shows a plain neutral '·' in that slot.",
        "Eyeball the title column down a mixed list (some started, some watched, some "
        "untouched): the titles stay vertically aligned — the indicator never adds or "
        "removes a column.",
    ),
)
