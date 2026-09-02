from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=550,
    version="0.84.0",
    date="2026-09-02",
    title="Two more startup freezes gone, and a restored search stays on screen",
    items=(
        "Two launch freezes named by the new stall sampler are gone — the "
        "provider connection-test read and the migration pending-check both "
        "ran their database work on the UI thread.",
        "The restored search no longer blanks while the filter panel "
        "initializes.",
    ),
    test_steps=(
        "Cold-launch on a large library and check the log: no 'UI thread "
        "unresponsive' warning whose sampled MainThread stack names "
        "test_all_providers or migration needs_run.",
        "Launch with a restored search: the result list stays populated "
        "while the filter panel fills in — no multi-second blank.",
    ),
)
