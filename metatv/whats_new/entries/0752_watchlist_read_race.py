from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=752,
    version="0.189.0",
    date="2026-10-19",
    title="A removed watch rule no longer flickers back",
    items=("Removing (or editing) a Watch Alerts rule while the database was busy could "
           "show the old rule again for one refresh before it settled. Reads now account "
           "for every change still being saved, so the list shows the change at once and "
           "keeps showing it.",),
    test_steps=("Open Watch Alerts, add a rule, then remove it — it disappears at once and "
                "does not reappear on the next refresh.",),
)
