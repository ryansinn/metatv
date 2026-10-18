from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=727,
    version="0.165.0",
    date="2026-10-18",
    title="An experimental Windows build, and a setting that did nothing is gone",
    items=("The rolling release now carries MetaTV-windows-x64.zip: unzip it anywhere and run "
           "MetaTV.exe. mpv is included. It is unsigned, so Windows SmartScreen asks once "
           "(More info → Run anyway). Experimental: it has not been tested on Windows yet.",
           "Settings → Playback offered mpv, VLC and 'custom', but MetaTV has always played "
           "through mpv whatever was chosen. The choice is gone until a second player "
           "actually exists.",
           "Where MetaTV keeps its config, database, caches and downloads is now decided in "
           "one place. Existing folders are unchanged. On a new macOS install, downloads "
           "default to ~/Movies/MetaTV rather than a ~/Videos folder macOS doesn't have.",
           "Stream diagnostics now read the codec, resolution and bitrate with the mpv "
           "MetaTV ships, the same probe as 'Get stream details', instead of needing "
           "ffprobe installed. Packaged builds never included ffprobe, so these fields "
           "were usually blank there.",
           "The signal check (the black-screen / frozen / silent test) now identifies itself "
           "with the same browser User-Agent mpv plays with. Before, a source that filters "
           "on User-Agent could make it report a stream as dead that plays fine.",
           "Recordings keep the characters of their title that every system allows: "
           "'The Film (2024)' instead of 'The Film _2024_'. A title that is a reserved "
           "Windows name, such as 'Con', gets a trailing _ so the library still copies to a "
           "Windows drive.",
           "The stream-details probe now opens its mpv control socket in your private "
           "runtime folder instead of the shared /tmp."),
    test_steps=("Open Settings → Playback — there is no 'Preferred player' row; 'Player mode' "
                "and the autoplay options are still there. Play a channel — it opens in mpv.",
                "Open Settings → Downloads — the folder shows your existing downloads folder, "
                "unchanged. Download a VOD — it lands there.",
                "Select a movie and click 'Get stream details' in the details pane — the tracks and "
                "bitrate appear as before.",
                "Run a stream diagnostic on a channel — the result shows its codec and "
                "resolution (e.g. h264, 1920x1080), with no ffprobe installed.",
                "On a Windows PC, download MetaTV-windows-x64.zip from the rolling release, unzip "
                "it, run MetaTV.exe and choose Run anyway — the window opens; add a source and "
                "play a channel — it plays in mpv."),
)
