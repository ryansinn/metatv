from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=653,
    version="0.113.0",
    date="2026-09-08",
    title="Play All titles now show up in History",
    items=(
        "Play All (multi-select a channel list or an episode tree, then \"Play "
        "All\") queued everything up correctly, but never counted any of it: no "
        "play count bump, nothing in History, for any item in the selection — a "
        "fifth gap in the same \"record a play\" family fixed for Reactivate & "
        "Play and episode playback a release ago.",
        "Fixed the same way: each item is recorded at the moment it actually "
        "reaches mpv — the first item once it's confirmed playing, and each "
        "queued item as it's handed to mpv's playlist — never all of them up "
        "front before anything has actually launched. An item that fails to "
        "launch or fails to queue is not recorded; a real quit or stream failure "
        "no longer leaves a phantom entry behind.",
    ),
    test_steps=(
        "Multi-select 3+ channels or movies, choose Play All from the context "
        "menu — the first one plays; open History and confirm it now appears "
        "with its play count bumped.",
        "In a series' episode tree, multi-select several episodes and choose "
        "Play All — check History shortly after; each episode that mpv actually "
        "played (started or auto-advanced through) appears.",
        "Multi-select several channels including one with a broken stream URL, "
        "Play All — the working ones still record; the broken one does not.",
    ),
)
