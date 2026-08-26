from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=372,
    version="0.41.0",
    date="2026-08-26",
    title="The stray info mark on Stream Monitoring is gone",
    items=(
        "Stream Monitoring had a small info mark beside its count that looked "
        "clickable and was not - it only held a tooltip. Its explanation now "
        "lives on the heading itself, which you can already hover.",
    ),
    test_steps=(
        "Look at the Stream Monitoring heading - it reads as the name and a "
        "count, with nothing after it.",
        "Hover the heading - the tooltip explains what Stream Monitoring does, "
        "that you get a notification when a stream recovers, and that "
        "double-clicking an entry retries it.",
    ),
)
