from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=392,
    version="0.50.0",
    date="2026-08-27",
    title="Failures that used to disappear now say something",
    items=(
        "Forty places in the app caught an error and threw it away without a "
        "word. Some of them mattered: saving your panel layout could fail and "
        "the app would keep pretending it had worked, so your layout quietly "
        "stopped being remembered.",
        "Testing all of a source's URLs could fail and hand back an empty "
        "list, which looks exactly like 'every URL is down'. It now says what "
        "went wrong.",
        "Several database steps caught everything while meaning to catch one "
        "specific thing - a migration step meant to ignore 'this column "
        "already exists' was also ignoring 'the database is locked' and 'the "
        "disk is full', both of which then looked like a successful upgrade.",
    ),
    test_steps=(
        "Drag the filter panel wider, close the app, reopen it - the width "
        "should be remembered, and if it ever is not, the log now says why.",
        "Open a source for editing and use Test All URLs - results should "
        "appear as before; an outright failure now reports a reason instead "
        "of an empty list.",
        "Open Settings and change something, click OK, reopen - the setting "
        "must persist.",
        "Open the EPG Browse tab, drag a column to reorder it, restart, and "
        "confirm the order is restored.",
        "Open Sources and check the account info panel still shows expiry and "
        "creation dates for a provider that reports them.",
        "Check the log after a normal session - there should be no new noise; "
        "the point is that a real failure appears, not that ordinary use logs "
        "more.",
    ),
)
