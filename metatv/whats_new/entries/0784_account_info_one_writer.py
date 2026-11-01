from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=784,
    version="0.220.0",
    date="2026-11-01",
    title="A source renewed to an unlimited plan no longer stays marked expired",
    items=("When a source's account reported no expiry date — which is how an unlimited plan "
           "shows up — the catalogue refresh kept the old expiry date, so a renewed source could "
           "stay marked expired and hidden. It now clears the date, the same as the Sources editor "
           "always did. A garbled date from a provider no longer throws away the rest of the "
           "account check either.",),
    test_steps=("Refresh a source whose plan has no expiry — Sources shows no expiry date for it and "
                "it is not marked expired.",
                "Open Sources → a source → Summary — the account status, limit and dates still show "
                "as before.",),
)
