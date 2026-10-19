from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=738,
    version="0.175.0",
    date="2026-10-19",
    title="Column dividers are easier to grab on Mac",
    items=("On macOS the dividers between the sidebar, the list and the details pane are "
           "wider and show the resize arrows when you hover, so they are easy to find and "
           "drag. Clicking a divider still collapses or expands its panel. Linux and "
           "Windows are unchanged.",),
    test_steps=("On a Mac, hover the divider between the sidebar and the list — the cursor "
                "becomes left-right resize arrows; drag it and the sidebar resizes.",
                "Click the same divider without dragging — the sidebar collapses; click "
                "again — it comes back at the same width.",
                "Repeat on the divider between the list and the details pane."),
)
