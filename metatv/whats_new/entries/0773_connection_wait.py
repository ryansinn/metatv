from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=773,
    version="0.209.0",
    date="2026-10-31",
    title="A source at its connection limit: MetaTV waits, then starts the title",
    items=("When a source turns a play away because every connection is in use — usually a "
           "stream that just ended and the source is still counting — MetaTV no longer just "
           "says it failed. It checks the account every 30 seconds and starts the title as soon "
           "as a connection frees up. Cancel stops the wait, and so does playing something else.",
           "Each wait is recorded, and the Sources editor's Analytics tab has a new Connections "
           "section: the source's limit, how long it usually takes to free one, and the longest "
           "wait so far.",),
    test_steps=("Play something from a one-connection source, close the player, and at once play "
                "something else from it — a \"Waiting for a connection on <source>\" notification "
                "appears with a Cancel button, instead of \"Stream did not start\".",
                "Leave it — when the source frees the connection the title starts by itself and "
                "the status bar says how long it took.",
                "Open Sources → that source → Analytics — Connections shows the limit and "
                "\"Usually frees up within\" with that wait.",
                "Trigger another wait and press Cancel — the notification goes and nothing starts.",
                "With a source that has no waits yet, Connections explains what it will show.",),
)
