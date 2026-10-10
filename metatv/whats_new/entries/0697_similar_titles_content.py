from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=697,
    version="0.140.0",
    date="2026-10-09",
    title='Similar: Titles or Content',
    items=("The Similar section has a [Titles | Content] switch. Titles matches names across movies AND series; Content shows TMDb's recommendations that are in your library. Your choice is remembered.",),
    test_steps=('Select a film with a TMDb match — Similar shows a Titles/Content switch; Titles now includes series with matching names.', "Switch to Content — the list becomes TMDb's recommendations you can play; switch back — the name matches return.", 'Restart — the switch is where you left it.'),
)
