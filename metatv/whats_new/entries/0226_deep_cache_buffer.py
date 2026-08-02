from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=226,
    version="0.19.0",
    date="2026-08-01",
    title="Deep-cache: \"Buffer without limit\" for movies & series",
    items=(
        "A new per-title action, \"Buffer without limit (pre-load fully)\", is "
        "available on movies and series (not live channels) from the right-click "
        "menu. It relaunches mpv with the open-ended disk-backed cache PLUS a "
        "scratch stream-record file, so the buffer can grow further than the "
        "normal cache allows — useful for a title on a very unstable source. "
        "The recording is temporary: it's purged automatically when playback "
        "stops or the window is reused, and any leftover file is swept on the "
        "next app start. A soft cap (20 GiB by default, configurable) evicts "
        "the oldest recordings first, and the action refuses to start (with an "
        "explanation) if there isn't enough free disk space.",
    ),
    test_steps=(
        "Right-click a movie or series episode in the channel list → the menu "
        "shows \"Buffer without limit (pre-load fully)\" (disk icon); right-click "
        "a LIVE channel → the action is NOT shown.",
        "Click \"Buffer without limit (pre-load fully)\" on a movie → playback "
        "starts (mpv relaunches with the deep-cache flags) and a scratch "
        "recording file appears under the deep-cache directory "
        "(~/.cache/metatv/deepcache/ by default) while it plays.",
        "Stop playback → the scratch recording file for that title is removed "
        "shortly after.",
    ),
)
