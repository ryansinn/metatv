from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=747,
    version="0.184.0",
    date="2026-10-19",
    title="Dialogs use the same clean icons",
    items=("The source editor, Add Source, Settings, Global Exclusions, categories, stream "
           "diagnostics, the log viewer, What's New, About and the Watch Alert dialogs now use "
           "the app's one icon set instead of emoji.",),
    test_steps=("Open Sources and select a source — Refresh, Analyze, Refresh Guide and Delete "
                "show line icons; Test Connection reports \"N/N working\" with a check icon.",
                "Open Help → About and Tools → Log viewer — titles and buttons lead with line "
                "icons, no emoji.",
                "Add a Watch Alert from a series — the Movie / Series choice shows icons beside "
                "the words."),
)
