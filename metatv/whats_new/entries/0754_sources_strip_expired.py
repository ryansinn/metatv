from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=754,
    version="0.191.0",
    date="2026-10-20",
    title="The Sources footer no longer calls lapsed sources 'expiring'",
    items=("A subscription that has already ended now reads 'expired', never "
           "'expiring'. A source you turned off after it expired no longer counts "
           "toward the warning at all.",),
    test_steps=("With one working source and a turned-off source whose subscription "
                "has ended, look at the Sources footer above Settings — it reads "
                "'1 active', not 'expiring'.",),
)
