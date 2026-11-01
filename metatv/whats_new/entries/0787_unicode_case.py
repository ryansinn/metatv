from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=787,
    version="0.223.0",
    date="2026-11-01",
    title="Search ignores case for accented letters too",
    items=("Searching \"école\" now finds \"ÉCOLE\", and the same for Ş, Ö, Ñ and every other accented "
           "or non-Latin capital — in search, filters, watch alerts and tags. Before, only A–Z were "
           "matched regardless of case (\"école\" found 22 of your 33 matching titles).",),
    test_steps=("Search for a title in lowercase whose name is in capitals with an accent (e.g. "
                "\"école\" for \"ÉCOLE…\") — it is found.",
                "Add a watch alert for a lowercase accented word — channels with it in capitals match.",),
)
