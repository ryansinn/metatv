from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=759,
    version="0.196.0",
    date="2026-10-20",
    title="Country codes show their names in Global Exclusions",
    items=("Codes such as BO, CR, CU, DO and EC now read Bolivia, Costa Rica, Cuba, "
           "Dominican Republic and Ecuador, along with about sixty other countries the "
           "exclusion lists named only by code. Codes that mean two different things in "
           "provider data stay as codes.",),
    test_steps=("Open Global Exclusions and expand Spanish — every country code shows its "
                "name, e.g. [BO] Bolivia and [CR] Costa Rica.",),
)
