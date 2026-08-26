from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=353,
    version="0.41.0",
    date="2026-08-25",
    title="Sidebar headers lose the caret; alert actions move up",
    items=(
        "Section headers have no collapse caret. The whole header has been "
        "clickable since #329 and carries the pointing-hand cursor, so the "
        "caret was a second affordance for one action — 16px of a 300px "
        "header spent on a hint the cursor already gives.",
        "Watch Alerts' settings and + buttons sit on the section header line "
        "instead of on a sub-group's heading. They govern keyword rules and "
        "monitored series across every sub-group, so sitting on one of them "
        "said they belonged to it.",
    ),
    test_steps=(
        "Look at any sidebar section header → there is no ⌄ or › caret, just "
        "the title, its count or news, and the → arrow.",
        "Click a section header anywhere → it collapses; click again → it "
        "expands. Hover it → the cursor is a pointing hand and the tooltip "
        "says it collapses or expands.",
        "Collapse a section, restart the app → it comes back collapsed.",
        "Watch Alerts → the sliders and + buttons are on the \"Watch Alerts\" "
        "header line itself, not beside EPG or Movies & Series.",
        "Click the sliders button → the manage dialog opens. Click + → the "
        "\"watch for new content\" flow starts. Hover each → a tooltip names it.",
    ),
)
