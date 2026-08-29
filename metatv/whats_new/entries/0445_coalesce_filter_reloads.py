from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=445,
    version="0.55.0",
    date="2026-08-29",
    title="Changing filters reloads the list once, not once per control",
    items=(
        "Every filter control reloaded the channel list the moment it changed. "
        "One action that touches several controls - restoring your saved "
        "filters at startup, pressing Clear, a chip that implies others - ran "
        "a full search of the library for each one.",
        "A startup log showed five of those searches in seven seconds, each "
        "over 785,162 channels, with only the last one's results kept.",
        "The list now waits for the controls to settle and searches once.",
        "A single filter change is unaffected, and two separate actions still "
        "produce two searches.",
    ),
    test_steps=(
        "Press Clear with several filters active and confirm the list updates "
        "once rather than flickering through intermediate results.",
        "Change one filter and confirm the list updates normally.",
        "Change a filter, wait, change another, and confirm both take effect.",
        "Restart with saved filters and confirm the list is correct.",
    ),
)
