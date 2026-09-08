from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=632,
    version="0.103.0",
    date="2026-09-08",
    title="A spinner whose panel was torn down no longer crashes",
    items=(
        "The Watch Alerts busy spinner is animated by a timer that kept ticking "
        "after the widget it painted was gone — a logged error at best, a crash "
        "when the tick landed mid-teardown. The tick now stops itself when its "
        "widget is gone.",
    ),
    test_steps=(
        "Start a monitored-series check (the spinner shows in the Watch Alerts "
        "header), then collapse and re-expand the section and switch views while "
        "it runs → no error in the log, no crash.",
    ),
)
