from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=596,
    version="0.97.0",
    date="2026-09-05",
    title="Guide rows get a Record control, recording indicators, and one persistent recording notice",
    items=(
        "Every guide row — Watch Alerts, On Now, and Browse — now carries a "
        "Record control, so you can schedule a recording straight from the "
        "row instead of only through the channel menu.",
        "A row whose channel is already recording or already scheduled shows "
        "that state on the control itself (a distinct glyph, with a tooltip "
        "naming when it started or when it's due), so you can tell at a "
        "glance without opening a menu.",
        "While a recording runs, one persistent notice reports how far in it "
        "is, roughly how much is left, how much disk it's used and how much "
        "is free, and when it ends — with Watch (open what's recorded so "
        "far) and Stop buttons right on the notice.",
    ),
    test_steps=(
        "In On Now, click the ● control on a programme row — it schedules a "
        "recording, and the cell switches to the scheduled indicator.",
        "When the recording starts, the cell switches to the recording "
        "indicator and a persistent notice appears with elapsed/remaining "
        "time, disk space, and Watch/Stop buttons.",
        "Click Watch on the notice — it plays the file being written, and "
        "the notice stays up. Click Stop — the recording ends and the "
        "notice disappears.",
        "Repeat the click-to-schedule check on a Browse row and a Watch "
        "Alerts row.",
    ),
)
