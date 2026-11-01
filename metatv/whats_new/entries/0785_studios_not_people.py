from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=785,
    version="0.221.0",
    date="2026-11-01",
    title="Studios no longer show up as directors",
    items=("Series metadata often lists the production company as the director — \"A+E Studios\", "
           "\"CBS Television Studios\", \"Sony Pictures Television\" — and MetaTV filed those as "
           "people. They no longer appear among a title's directors or in person filters, and the "
           "ones already stored are removed on the next launch.",),
    test_steps=("Launch MetaTV — the startup tasks include \"Removing studios listed as people\".",
                "Open a series such as YOU or Knightfall — its directors list people only, no "
                "\"A+E Studios\".",
                "Filter by person — no studio names in the list.",),
)
