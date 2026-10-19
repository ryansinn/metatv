from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=748,
    version="0.185.0",
    date="2026-10-19",
    title="Series tree, Tools views and Recommended use the same clean icons",
    items=("The series tree shows each season's state as one icon — a check when watched, a "
           "half circle when partly watched, a folder otherwise — and episodes use the same "
           "watch-progress icons. The Tools views (Reconnect, Missing TMDb Data, Metadata "
           "Enrichment), the downloads menu and the Recommended view use the app's one icon set.",),
    test_steps=("Open a series with some episodes watched — each episode row's icon shows its "
                "progress; a fully-watched season shows a check icon, a partly-watched one a half "
                "circle.",
                "Open Tools → Missing TMDb Data — the headings and counts lead with line icons, "
                "no emoji."),
)
