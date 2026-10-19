from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=741,
    version="0.178.0",
    date="2026-10-19",
    title="Right-click menus use the same clean icons",
    items=("Every icon in a channel's right-click menu now comes from the app's one icon "
           "set instead of emoji drawn grey — sharper, and items that used to share a "
           "symbol (Play and Play from Beginning, for one) now look different.",),
    test_steps=("Right-click a movie you've partly watched — Play (orange, \"Play from M:SS\") "
                "and Play from Beginning (grey, a replay arrow) have different icons.",
                "Right-click any channel — every icon in the menu is a single-colour line "
                "icon, none a colour emoji; Favourites shows a heart; Watch Later a bookmark."),
)
