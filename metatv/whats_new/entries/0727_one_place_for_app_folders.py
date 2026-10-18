from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=727,
    version="0.165.0",
    date="2026-10-18",
    title="Removed the 'Preferred player' setting, which did nothing",
    items=("Settings → Playback offered mpv, VLC and 'custom', but MetaTV has always played "
           "through mpv whatever was chosen. The choice is gone until a second player "
           "actually exists.",
           "Where MetaTV keeps its config, database, caches and downloads is now decided in "
           "one place. Existing folders are unchanged. On a new macOS install, downloads "
           "default to ~/Movies/MetaTV rather than a ~/Videos folder macOS doesn't have.",
           "The stream-details probe now opens its mpv control socket in your private "
           "runtime folder instead of the shared /tmp."),
    test_steps=("Open Settings → Playback — there is no 'Preferred player' row; 'Player mode' "
                "and the autoplay options are still there. Play a channel — it opens in mpv.",
                "Open Settings → Downloads — the folder shows your existing downloads folder, "
                "unchanged. Download a VOD — it lands there.",
                "Select a movie and click 'Get stream details' in the details pane — the tracks and "
                "bitrate appear as before."),
)
