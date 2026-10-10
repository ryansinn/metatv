from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=695,
    version="0.140.0",
    date="2026-10-09",
    title='Episodes are measured too',
    items=('Playing an episode now records its real resolution, codecs, bitrate and tracks; selecting that episode shows them in Details.',),
    test_steps=("Play an episode for a few seconds, then select it in the series tree — Details shows Resolution / Video / Audio rows with '· seen when played'.", 'Select a different, unplayed episode — those rows are gone (they belong to the other episode).'),
)
