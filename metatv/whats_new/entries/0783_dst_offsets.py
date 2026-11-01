from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=783,
    version="0.219.0",
    date="2026-11-01",
    title="Times on the other side of a daylight-saving change are no longer an hour off",
    items=("MetaTV converted every stored time with today's clock offset. After the clocks "
           "change, anything from before the change — guide entries, watch history, a "
           "recording scheduled across it — showed an hour off. Each time now uses its own "
           "date's offset, and a day with a clock change counts as 23 or 25 hours.",),
    test_steps=("Open History or a past guide day from before the most recent clock change — the "
                "times match what you saw then.",
                "Schedule a recording for a date on the other side of a clock change — it starts "
                "at the time you entered.",),
)
