from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=177,
    version="0.14.1",
    date="2026-07-31",
    title="Favorited items now show a clear gold star",
    items=(
        "A favorited title's ★ in the details rail now glows gold, so a favorite is "
        "unmistakable at a glance. Before, the active star was a faint gray on a gray "
        "button — almost impossible to tell apart from an unfavorited one.",
    ),
    test_steps=(
        "Select a channel and click the ☆ Favorite button in the details rail: it "
        "fills to a GOLD ★ (gold star, gold border, gold-tinted background), clearly "
        "distinct from the dim unfavorited state. Click again to un-favorite → it "
        "reverts to the faint outline.",
    ),
)
