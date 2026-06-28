from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=76,
    version="0.8.0",
    date="2026-06-28",
    title="Details pane: rating on type line + sentiment rail left of poster",
    items=(
        "Star rating and content-rating badge (e.g. PG-13) now appear right-aligned"
        " on the same line as the content type (e.g. 'Series'), removing a separate"
        " row and reclaiming vertical space.",
        "Like / Not Interested / Dislike buttons are now a vertical bordered-chip rail"
        " to the left of the poster on VOD titles, replacing the flat horizontal row"
        " below the action buttons.",
    ),
    test_steps=(
        "Open a VOD movie or series with a rating — 'Series' or 'Movie' line should show"
        " the star rating (e.g. ★★★★ 8.0 of 10) right-aligned on the same row, with no"
        " separate rating row below it.",
        "Open a VOD title with a content rating (PG-13 / R / etc.) — badge should appear"
        " between the IMDb/TMDb IDs and the star rating on the type line.",
        "Open a VOD title — three bordered chip buttons (👍 / 🚫 / 👎) should appear as a"
        " vertical stack to the LEFT of the poster image.",
        "Click 👍 Like → button becomes checked/highlighted. Click again → unchecked."
        " Verify 👎 Dislike is mutually exclusive (checking one unchecks the other).",
        "Switch to a live channel — the sentiment rail and poster should both be hidden;"
        " only the live header and action rows are visible.",
        "Open a VOD title with no rating — the type line should show only 'Movie' (or"
        " 'Series') with no empty gap on the right.",
    ),
)
