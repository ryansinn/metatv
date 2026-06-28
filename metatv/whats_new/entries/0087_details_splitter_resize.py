from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=87,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane is resizable again + splitter drags no longer thrash the config",
    items=(
        "The details pane resize handle works again — you can drag it to widen "
        "or narrow the pane (300–500px). It was pinned to a fixed width, so the "
        "handle did nothing.",
        "Dragging any splitter (sidebar, details, or filter panel) no longer "
        "rewrites the config file on every pixel of movement — saves are now "
        "debounced into a single write ~0.5s after you let go, ending the burst "
        "of dozens of config saves/backups per drag.",
    ),
    test_steps=(
        "Select a channel so the details pane shows. Drag the handle between the "
        "channel list and the details pane left/right — the details pane should "
        "actually resize (between ~300 and ~500px), not stay fixed.",
        "Resize the details pane, then close and reopen the app — the pane should "
        "reopen at the width you left it at.",
        "With the app's debug log visible, drag a splitter back and forth "
        "continuously. You should see at most ONE 'Saved splitter sizes' / config "
        "save shortly AFTER you release the drag, not a stream of saves during it.",
    ),
)
