from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=503,
    version="0.64.0",
    date="2026-09-01",
    title="MetaTV rewrote your settings file even when nothing had changed",
    items=(
        "Anything that could change a setting asked for the file to be saved, "
        "and the app never checked whether there was anything new to write — "
        "so nudging a divider back to where it started, or toggling a section "
        "twice, cost the same as a real change.",
        "It now writes only when something actually differs. On a large "
        "settings file that is the difference between a noticeable pause and "
        "nothing at all.",
        "Your edits are unaffected: the check compares the real current state, "
        "so a change made any way at all is still saved.",
    ),
    test_steps=(
        "Drag a sidebar divider and let go, then repeat without moving it — "
        "the second one should feel instant.",
        ("Change a setting, click OK, close and reopen MetaTV, and confirm it "
         "was kept.", "view:list"),
        "Hide a Discover shelf, restart, and confirm it is still hidden.",
        "Add a series to your watch list, restart, and confirm it is still there.",
    ),
)
