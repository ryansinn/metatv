from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=576,
    version="0.91.0",
    date="2026-09-03",
    title="The Preferences dashboard stops computing while closed",
    items=(
        "Every source or enrichment change used to re-run the full "
        "recommendation engine for the Preferences dashboard even when it "
        "was closed — one of the biggest hidden contributors to launch-time "
        "stutter. A closed dashboard now does nothing; opening it computes "
        "fresh, as it always did.",
        "Re-opening Preferences after switching away no longer risks a "
        "crash — its background worker is rebuilt on return instead of "
        "being submitted to after shutdown.",
    ),
    test_steps=(
        "Launch the app and use it WITHOUT opening Preferences while a "
        "source refresh runs → no multi-second recommendation stalls "
        "attributable to the closed dashboard.",
        "Open Preferences → it loads fresh; switch to another view and "
        "back → it loads again without error.",
    ),
)
