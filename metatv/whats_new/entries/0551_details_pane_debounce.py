from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=551,
    version="0.85.0",
    date="2026-09-02",
    title="Details pane render debounce",
    items=(
        "Selecting a title no longer renders the details pane (and fetches "
        "its metadata) twice when the click reaches it through two surfaces "
        "at once.",
        "Clicking the same row again on purpose still refreshes it.",
    ),
    test_steps=(
        "Click through several titles quickly and check the log: one "
        "'render request' line per gesture, with any duplicate suppressed "
        "within 300ms.",
        "Click the same row again after watching something: the pane still "
        "re-renders (the deliberate refresh keeps working).",
    ),
)
