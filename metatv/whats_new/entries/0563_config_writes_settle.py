from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=563,
    version="0.86.0",
    date="2026-09-03",
    title="UI-state config writes settle to one per burst",
    items=(
        "Dragging a splitter, resizing a sidebar section, toggling a filter/sort/"
        "collapse control, or reordering a list no longer writes the 129 KB config "
        "file (plus a full backup copy) on every tick — the write now settles to "
        "ONE, 1.5 seconds after you stop. The owner's log showed ~18 full save+"
        "backup cycles in six minutes from ordinary UI interaction; the in-memory "
        "value still updates instantly, only the disk write is deferred, and it "
        "always flushes on quit.",
    ),
    test_steps=(
        "Drag the sidebar splitter around for a few seconds → the log shows ONE "
        "'Saved config'/write cycle after you stop, not one per tick.",
        "Quit the app right after dragging a splitter or toggling a filter → "
        "relaunch → the change is still there (the final save on close flushed it).",
        "Toggle a details-pane section (e.g. Cast) open/closed a few times quickly "
        "→ no per-click stutter, and the collapsed state is remembered next launch.",
    ),
)
