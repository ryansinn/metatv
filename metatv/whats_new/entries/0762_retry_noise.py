from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=762,
    version="0.199.0",
    date="2026-10-20",
    title="Less retrying against your source",
    items=("Re-checking streams that failed to play is now off by default (Settings → "
           "Playback → Network). Each re-check is a real stream connection, which on an "
           "account with one connection can block your own playback. Failed streams are "
           "still counted, so channels that keep failing are still held back.",
           "When a source says all its connections are in use, MetaTV no longer tries the "
           "title's other versions on that same source — only copies on other sources.",
           "mpv no longer makes an extra fallback request for a source's stream after it "
           "fails to open. Trailers still use that fallback."),
    test_steps=("Open Settings → Playback → Network — \"Re-check streams that failed to "
                "play\" is unticked and \"Re-check failed streams on source refresh\" is "
                "greyed out; tick the first and the second becomes available.",),
)
