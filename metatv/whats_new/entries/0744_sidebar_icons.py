from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=744,
    version="0.181.0",
    date="2026-10-19",
    title="Sidebar: clean icons in menus, notices and the Sources strip",
    items=("The sidebar's ⋯ menus (Clear history, Open downloads folder…), its loading and "
           "error rows, the stream-recovery list and the Sources strip use the app's one "
           "icon set. Stream recovery shows a green or red icon with its own shape, not a "
           "coloured dot alone.",),
    test_steps=("Open the ⋯ menu on the History section — each item has a line icon in the "
                "icon column and no emoji in its text.",
                "Look at the Sources strip at the bottom of the sidebar — \"Sources\" and its "
                "summary (e.g. \"3 active\") lead with line icons.",
                "With a source disabled, open Sources — its status dot is a struck-out circle, "
                "distinct from an active source's filled dot."),
)
