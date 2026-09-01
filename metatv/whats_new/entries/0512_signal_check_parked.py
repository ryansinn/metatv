from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=512,
    version="0.66.0",
    date="2026-09-01",
    title="Dead-stream checking is switched off",
    items=(
        "The check that looks for dead air was taking your source's "
        "connection every few seconds, all the time. On an account with a "
        "single connection that is the connection — so it competed with "
        "whatever you were watching, and with itself.",
        "It was also wrong about what it found. Channels that were playing "
        "perfectly came back marked dead, because a stream it could not open "
        "(usually: the connection was already in use) looks the same to it as "
        "a stream with nothing on it.",
        "It is off, and the marks it recorded are cleared so nothing gets "
        "hidden on the strength of them. The idea is a good one and will come "
        "back once it can tell a busy connection from an empty channel.",
    ),
    test_steps=(
        ("Launch MetaTV and confirm the log has no 'signal check:' probe lines "
         "after startup."),
        ("Play something and confirm it starts without competing for the "
         "connection.", "view:browse"),
        ("Open Events and confirm nothing is hidden as dead.", "view:events"),
        ("Check the log for the one-time 'cleared N signal-check verdict(s)' "
         "line on first launch."),
    ),
)
