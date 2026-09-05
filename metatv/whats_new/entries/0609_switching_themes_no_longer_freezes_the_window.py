from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=609,
    version="0.99.0",
    date="2026-09-05",
    title="Switching themes no longer freezes the window for seconds",
    items=(
        "A palette switch now repaints the window once at the end instead "
        "of after every widget, so it no longer freezes for several "
        "seconds with a large library open.",
        "No widget is styled twice during a switch anymore.",
    ),
    test_steps=(
        "Settings > Appearance > switch Midnight to Daylight with a large "
        "library open — the window changes in well under a second, no "
        "grey flash.",
        "Every panel shows the new palette (sidebar, list rows, details "
        "pane, dialogs opened afterwards).",
    ),
)
