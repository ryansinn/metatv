from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=743,
    version="0.180.0",
    date="2026-10-19",
    title="Menus and main buttons use the same clean icons",
    items=("The Tools and Help menus, the Settings button, the Downloaded / Hidden search "
           "tabs and the guide's Refresh button now show the app's one set of icons "
           "instead of emoji.",),
    test_steps=("Open the Tools menu — every item has a single-colour line icon in the icon "
                "column, with no emoji in the text.",
                "Look at the Settings button at the bottom of the sidebar and the Downloaded / "
                "Hidden tabs above the list — each shows a line icon beside its word."),
)
