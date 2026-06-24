from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=45,
    version="0.7.3",
    date="2026-06-23",
    title="Your ratings are now visible in the channel list",
    items=(
        "Liked channels now show a 👍 glyph at the end of their row; "
        "disliked channels show 👎. Unrated channels look the same as before.",
        "The glyph is a trailing indicator — it sits after the title and category "
        "so it never disturbs alignment or the watch-progress icon.",
        "Hover over any rated row to see the tooltip: "
        '"You rated this 👍" or "You rated this 👎".',
    ),
    test_steps=(
        "Rate a channel 👍 via the details pane → the row in the channel list should show a 👍 glyph at the end.",
        "Rate a channel 👎 → channel list row shows 👎 glyph (unrated rows show no glyph).",
        "Hover over a rated row → tooltip reads 'You rated this 👍' or 'You rated this 👎'.",
    ),
)
