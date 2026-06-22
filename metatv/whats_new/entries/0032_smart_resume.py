from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=32,
    version="0.7.8",
    date="2026-06-22",
    title="Smart Resume + Still Watching?",
    items=(
        "Smart resume: 'Continue watching' now picks up from the last episode "
        "you *deliberately* started, not the furthest auto-queued one. Episodes "
        "that the queue auto-advanced through while you may have dozed off no "
        "longer hijack your resume point.",
        "After the queue auto-advances through one or more episodes and the "
        "player closes, MetaTV asks 'Still watching? Did you watch them?' — "
        "Yes promotes those episodes from gray (auto-watched) to solid (fully "
        "engaged) and advances your resume anchor past them; No leaves your "
        "resume point where it was.",
        "The 'Still watching?' prompt can be turned off in Settings → Playback "
        "(\"Ask 'Still here?' after auto-advancing through episodes\").",
    ),
)
