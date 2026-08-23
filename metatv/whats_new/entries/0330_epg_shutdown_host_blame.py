from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=330,
    version="0.33.0",
    date="2026-08-22",
    title="Closing during a guide download no longer blames your sources",
    items=(
        "Quitting while an EPG guide was still downloading logged an alarming "
        "'EPG fetch failed' error, and sometimes flashed an EPG Error "
        "notification on the way out. Nothing had actually failed — the app "
        "was simply shutting down while the download was still running.",
        "The real harm was invisible: the app recorded that shutdown as the "
        "host being unreliable, and then tried each of the source's other "
        "hosts, recording a failure against every one of them too. Those "
        "counts decide which host gets tried first, so quitting mid-download "
        "quietly degraded the connection ranking for that source, over and "
        "over.",
        "A shutdown is now told apart from a genuine failure. It stops the "
        "download immediately, records nothing against any host, and exits "
        "without an error or a notification. Real host failures are still "
        "recorded exactly as before.",
    ),
    test_steps=(
        "Open Settings → EPG and start a guide refresh on a source with a "
        "large guide, then close the app while it is still downloading.",
        "Reopen the app and check the log in ~/.config/metatv/logs/ — there "
        "should be an 'EPG refresh ... abandoned' info line, and NO 'EPG "
        "fetch failed' or 'XMLTV fetch/parse error' entries from that close.",
        "Confirm no EPG Error notification appeared during that shutdown.",
        "Open the source in Sources → Edit and check its host list — the "
        "hosts should not have picked up new failure counts from the close.",
        "Now break a source on purpose (edit a host to an unreachable "
        "address) and refresh its guide → that host SHOULD still be recorded "
        "as failing, and the refresh should fall through to a working host.",
    ),
)
