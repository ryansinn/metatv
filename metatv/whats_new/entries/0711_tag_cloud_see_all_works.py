from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=711,
    version="0.151.0",
    date="2026-10-10",
    title="'See all' on tag cloud tiles works",
    items=("Each tag cloud tile's 'See all →' now opens that facet's full cloud — it was "
           "a label that only looked like a link.",),
    test_steps=("Open the Recipe browser, click 'See all →' on the Genre tile — the full "
                "Genre cloud opens, same as clicking the word 'Genre'.",),
)
