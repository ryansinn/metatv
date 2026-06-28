from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=102,
    version="0.9.0",
    date="2026-06-28",
    title="EPG Browse is now forward-looking: start anchors + endless scroll",
    items=(
        "Browse no longer asks you to pick a calendar day and a fixed time slot "
        "(Morning/Afternoon/Prime/Late Night). Instead it opens at NOW and lists "
        "what's coming up, in order — it never shows programmes that already aired "
        "(no more browsing 6 AM at 2 PM).",
        "A single 'Starting:' dropdown sets where the timeline begins — Now, Tonight, "
        "Tomorrow, Tomorrow Night (and This Weekend) — each labelled with the resolved "
        "local time. Pick one to jump the list forward to that point.",
        "The schedule loads in chunks and pulls in the next batch automatically as you "
        "scroll toward the bottom, so even a deep guide stays fast.",
        "New setting (Settings → Metadata & API Keys → EPG): 'Hide EPG older than (h)' "
        "trims the left edge of the guide timeline. This is Phase 1; a draggable "
        "timeline scrubber is planned next.",
    ),
    test_steps=(
        "Open EPG → Browse. Confirm it opens at 'Now' and the first row is an upcoming "
        "(not already-aired) programme, with later programmes listed in chronological "
        "order.",
        "Change the 'Starting:' dropdown to Tonight, then Tomorrow. Confirm the list "
        "jumps forward so the first programme starts at/after the chosen anchor (and "
        "never shows the past).",
        "Scroll to the bottom of the Browse list. Confirm more programmes load "
        "automatically (the count grows) until the guide runs out.",
        "Open Settings → Metadata & API Keys → EPG, change 'Hide EPG older than', click "
        "OK, reopen Settings, and confirm the value persisted.",
    ),
)
