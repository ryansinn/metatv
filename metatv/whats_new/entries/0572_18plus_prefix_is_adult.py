from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=572,
    version="0.89.0",
    date="2026-09-03",
    title="The \"18+\" prefix is now recognized as adult content",
    items=(
        "Channels shaped \"18+ - Title (Year)\" were invisible to the adult-content "
        "filter — the parser never captured the leading \"18+\" at all, so those "
        "titles carried no prefix chip and never counted as restricted. 466 rows "
        "on the reported library were affected.",
        "\"18+\" now joins the same Adult prefix group as X / XXX / ADULT / "
        "PORNBOX, so Content settings and Global Exclusions treat it the same way.",
        "Existing libraries are re-scanned automatically in the background so "
        "already-ingested \"18+\" titles pick up the fix without a re-add.",
    ),
    test_steps=(
        "With Content set to hide adult titles, search a \"18+ -\" title → it no "
        "longer appears; switch to Show Everything → it does, grouped under the "
        "Adult prefix group in Global Exclusions.",
        "Open a \"18+ - Title (Year)\" channel's details pane → the title renders "
        "clean (no leading \"18+ -\") and the Adult prefix chip is shown.",
    ),
)
