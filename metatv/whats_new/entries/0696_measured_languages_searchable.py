from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=696,
    version="0.140.0",
    date="2026-10-09",
    title='Languages heard in a stream are searchable',
    items=('A language measured in a played or probed stream becomes a language tag, so filtering or searching by that language finds the title.',),
    test_steps=('Play or probe a film whose audio is English but whose label says SE — filter the list by Language: English; the film appears.',),
)
