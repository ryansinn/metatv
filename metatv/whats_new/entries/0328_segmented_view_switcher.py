from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=328,
    version="0.40.0",
    date="2026-08-22",
    title="The five views are one switcher now",
    items=(
        "Search, EPG, Recommended, Discover and Recipe sat as five separate "
        "buttons with a wide gap between them. Nothing tied them together, so "
        "they read as five unrelated controls rather than as one choice of "
        "five — and the active one was a small filled lozenge that did not "
        "look especially active.",
        "They are now a single switcher: one outline around the group, a thin "
        "divider between each view, and the view you are in filling its whole "
        "section edge to edge.",
        "Because the filled section now shows which view is current, the "
        "little ● and ○ markers have been dropped from the labels.",
    ),
    test_steps=(
        "Look at the bottom bar — the five view buttons are joined into one "
        "group with a single outline around them and thin dividers between, "
        "not five separate buttons with gaps.",
        "Click through Search, EPG, Recommended, Discover and Recipe — the "
        "view you are in is filled solid across its entire section, top to "
        "bottom, with no gap above or below the fill.",
        "Check that the labels no longer show a ● or ○ after the view name.",
        "Open Settings → Style and switch between Midnight, Graphite and "
        "Daylight → the outline, the dividers and the filled section all "
        "change with the theme, and the active label stays readable on it.",
        "Widen and narrow the window → the group stays joined with no gaps "
        "opening between the sections.",
    ),
)
