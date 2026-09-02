from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=543,
    version="0.81.0",
    date="2026-09-02",
    title="History group trash clears instantly, with Undo",
    items=(
        "The trash icon on a History time-group heading no longer asks "
        "'Are you sure?' — it clears the group at once and a toast offers "
        "Undo for 8 seconds. A per-group misclick is cheap to fix; a "
        "library-wide wipe still deserves a question.",
        "A title you re-play before hitting Undo keeps its new history "
        "entry — Undo only restores rows nobody has touched since the "
        "clear, so it can never move history backwards.",
        "The two big clears — 'Clear history older than 30 days' and "
        "'Clear all history' — still show their confirmation dialog. "
        "Nothing changed there.",
    ),
    test_steps=(
        "Click the trash on a History time-group heading: the group clears "
        "immediately with no dialog, and a toast says how many were "
        "forgotten with an Undo button.",
        "Click Undo within 8 seconds: the group's entries return, favorites "
        "intact.",
        "Clear a group, replay one of its titles, then click Undo: the "
        "replayed title keeps its fresh history entry while the rest "
        "return.",
        "Use ⋯ → Clear all history: the confirmation dialog still "
        "appears.",
    ),
)
