from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=386,
    version="0.41.0",
    date="2026-08-27",
    title="Your provider password is no longer written to the log files",
    items=(
        "An Xtream stream URL contains your subscription username and "
        "password, and the app logged those URLs while playing, retrying and "
        "diagnosing streams. They were being written to the log files in "
        "~/.config/metatv/logs/ and kept for seven days.",
        "Credentials are now stripped from every log message before it is "
        "written - including the ?username=...&password=... form used when "
        "talking to the provider API, which was the bulk of it.",
        "Log lines stay useful: the host and the stream id are still there, "
        "only the credentials are replaced with ***.",
        "IF YOU HAVE SHARED A LOG FILE with anyone, or attached one to a bug "
        "report, treat your provider password as exposed and change it. "
        "Deleting ~/.config/metatv/logs/ clears the old files.",
    ),
    test_steps=(
        "Play any channel, then open the newest file in "
        "~/.config/metatv/logs/ and search it for your provider password - "
        "there should be no match.",
        "Search the same file for 'password=' - every occurrence should read "
        "password=*** and never a real value.",
        "Check a stream URL line still shows the host and the stream id, so "
        "the logs remain useful for diagnosing a bad source.",
        "Refresh a source and re-check the log - the provider API calls carry "
        "credentials in the query string and must be redacted too.",
        "Trigger a stream failure (disable a source's URL) and confirm the "
        "error lines are redacted as well - error paths are where full URLs "
        "were most often logged.",
    ),
)
