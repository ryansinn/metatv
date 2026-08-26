from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=365,
    version="0.41.0",
    date="2026-08-26",
    title="Fixed a crash in sidebar sections with grouped lists",
    items=(
        "Watch Alerts could take the app down as soon as its EPG list had any "
        "groups in it — a mistake in yesterday's sidebar scrolling change.",
    ),
    test_steps=(
        "Open the sidebar with Watch Alerts showing EPG entries → the app "
        "stays up and the groups render. This crashed before.",
        "Toggle Settings → Interface → Sidebar → \"Use 'Show N more' rows "
        "instead of scrollbars\" on and off a few times → no crash either way.",
    ),
)
