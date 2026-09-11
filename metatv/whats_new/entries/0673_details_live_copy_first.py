from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=673,
    version="0.123.0",
    date="2026-09-11",
    title="The details pane shows a copy you can play",
    items=(
        "Opening a title from History, Favorites, the Watch Queue or an "
        "alert used to show whichever copy that row pointed at — even one "
        "on a source that has since expired or been disabled — with the "
        "actually-playable copy folded away under \"Also Available\". The "
        "pane now shows a live copy first and says which source you were "
        "redirected from.",
        "A title with no live copy left still opens — the pane says the "
        "source is expired or disabled rather than showing nothing.",
    ),
    test_steps=(
        "With a title carried on two sources, disable one, then open it "
        "from Favorites/History/the Watch Queue pointing at the disabled "
        "copy — the pane shows the live copy, \"Source:\" names it, and a "
        "line under it says which copy was skipped and why.",
        "Disable both sources for that title — the pane still opens and "
        "the line says no other source carries it.",
        "Re-enable a source — the line disappears on the next open.",
    ),
)
