from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=114,
    version="0.9.0",
    date="2026-06-28",
    title="Pointing-hand cursor on clickable controls",
    items=(
        "Hovering a clickable control — buttons, filter chips, and the "
        "details action-rail buttons — now shows the pointing-hand cursor, "
        "making clickability obvious at a glance.",
        "Checkboxes and radio buttons keep the normal cursor (the box/circle "
        "is already the affordance), and disabled controls show no hand. "
        "Applied app-wide through a single hover filter, so every current and "
        "future button gets it automatically.",
    ),
    test_steps=(
        "Hover the mouse over any toolbar/filter chip or a button (e.g. a "
        "details action-rail button) → the cursor changes to a pointing hand.",
        "Hover over a checkbox or radio button (e.g. in Settings) → the cursor "
        "stays the normal arrow, not a hand.",
        "Hover over a disabled/greyed-out button → no pointing hand appears.",
    ),
)
