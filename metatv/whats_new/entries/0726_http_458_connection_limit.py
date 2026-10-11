from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=726,
    version="0.164.0",
    date="2026-10-11",
    title="HTTP 458 now says the account is at its connection limit",
    items=("Some sources answer 458 instead of 509 when every connection on the account is "
           "already in use. The bare 'HTTP 458' is replaced by the same explanation 509 gets: "
           "another device may be watching on this account.",
           "This applies to the 'Stream Unavailable' check before playback and to the "
           "report after a stream fails to start."),
    test_steps=("Start a stream on a one-connection source on another device, then play an "
                "episode from that source here — the 'Stream Unavailable' toast reads "
                "'(HTTP 458): this account is already using all of its connections'.",
                "Click Copy Error — the copied text still shows the raw 'HTTP 458'."),
)
