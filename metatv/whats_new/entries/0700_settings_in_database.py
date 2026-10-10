from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=700,
    version="0.140.0",
    date="2026-10-09",
    title='Settings are stored in the database',
    items=("Your preferences and remembered layout (pane sizes, filter state, EPG lists, theme choices and more) now live in MetaTV's database instead of config.yaml, migrated automatically on first launch.",),
    test_steps=("Launch once — the log says 'profile: migrated N key(s) from config.yaml to the database'; everything looks as you left it.", 'Change a setting (e.g. list density), restart — it sticks; config.yaml no longer changes.'),
)
