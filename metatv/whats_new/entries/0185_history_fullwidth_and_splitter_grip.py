from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=185,
    version="0.15.0",
    date="2026-07-31",
    title="Watch History fills the window · splitter handles show a grip",
    items=(
        "Opening the full Watch History now auto-collapses the sidebar and the "
        "details pane so the explorable trail-map gets the whole window instead "
        "of being boxed into the narrow middle panel. Switch to any other view "
        "and both panels spring back to the widths you had before.",
        "The splitter handles between the sidebar, content, and details pane now "
        "show a subtle grip and a pointing-hand cursor on hover, with a "
        "'Click to collapse/expand' tooltip — the click-to-collapse gesture used "
        "to be invisible. A single click collapses the panel; click again to "
        "bring it back.",
    ),
    test_steps=(
        (
            "Open Watch History via the sidebar History section's 'See all →' link "
            "→ the sidebar and details pane auto-collapse and the trail-map fills "
            "the window; switch to another view (e.g. Browse) → both panels restore "
            "to their prior widths.",
            "view:history",
        ),
        "Hover a splitter handle (between sidebar and content) → a visible grip "
        "appears, the cursor becomes a pointing hand, and a 'Click to "
        "collapse/expand' tooltip shows; single-click it → the panel collapses; "
        "click the handle again → it expands back to its previous width.",
    ),
)
