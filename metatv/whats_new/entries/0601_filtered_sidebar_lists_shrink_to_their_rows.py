from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=601,
    version="0.99.0",
    date="2026-09-05",
    title="A filtered sidebar list shrinks to its visible rows",
    items=(
        "A sidebar list that is filtered down now takes only the height of "
        "the rows still showing, instead of keeping blank space where the "
        "hidden rows were.",
    ),
    test_steps=(
        "Type in the Watch Queue filter so most rows hide — the section "
        "shrinks to the visible rows.",
        "Clear the filter — it grows back.",
    ),
)
