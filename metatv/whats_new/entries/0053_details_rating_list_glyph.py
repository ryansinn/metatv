from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=53,
    version="0.8.0",
    date="2026-06-24",
    title="Details-pane rating updates list row immediately",
    items=(
        "Rating a channel 👍 or 👎 from the details pane now updates the list-row "
        "glyph instantly — no reload required.",
        "Clearing a rating from the details pane removes the glyph from the list row "
        "in place.",
    ),
    test_steps=(
        "Select any channel in the list → rate it 👍 in the details pane → the same "
        "list row shows 👍 immediately without scrolling away or reloading.",
        "Click 👍 again in the details pane to clear the rating → the 👍 glyph "
        "disappears from the list row in place.",
        "Rate a channel 👎 → the list row shows 👎 immediately.",
        "Rate a channel that is not visible in the current list (e.g. a search with "
        "no matching results) → no error or crash.",
    ),
)
