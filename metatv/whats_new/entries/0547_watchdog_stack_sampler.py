from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=547,
    version="0.83.0",
    date="2026-09-02",
    title="Stall reports now name what was running",
    items=(
        "UI stall reports in the log now include a stack sample of every "
        "busy thread taken during the stall, so a freeze report names what "
        "was running instead of \"no phase open\".",
        "Catches both a blocked event loop and a GIL-starved one — a "
        "CPU-bound background worker that stalls the UI thread now shows "
        "up in the sample too.",
    ),
    test_steps=(
        "Trigger a UI stall (e.g. apply Global Exclusions on a large "
        "library) and check the log: the 'UI thread unresponsive' warning "
        "now carries 'sampled during stall' stack lines naming files and "
        "functions.",
    ),
)
