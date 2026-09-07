from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=616,
    version="0.101.0",
    date="2026-09-07",
    title="Recordings get their menu: Watch, Stop, Extend",
    items=(
        "Right-click a recording in the Recordings sidebar section for Watch, "
        "Stop recording and Extend +N minutes.",
        "The ⏺ RECORDING notice offers Extend too, alongside Watch and Stop — "
        "the one surface a live recording is always on.",
        "Before this, those actions existed and worked, but nothing in the "
        "interface actually reached them.",
    ),
    test_steps=(
        "Start a recording from the guide, right-click its row in Recordings "
        "— Stop recording and Extend +N min appear; Extend pushes the end "
        "time out by N minutes.",
        "The ⏺ RECORDING notice shows Watch, Stop and Extend.",
    ),
)
