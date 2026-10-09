from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=687,
    version="0.132.0",
    date="2026-10-09",
    title="Quieter Similar rows",
    items=(
        "Similar rows always offer Watch Later; favorite, watched, history, "
        "liked, disliked and not-interested marks appear only when they are set.",
    ),
    test_steps=(
        "Open a title's Similar list — rows you have never touched show only the "
        "title, year and the Watch Later button.",
        "Favorite one of those similar titles elsewhere, reopen — its row shows a "
        "gold star; click it — the favorite is removed.",
        "A title you finished shows ✓, one you marked Not interested shows its "
        "mark, a liked/disliked one shows its thumb.",
    ),
)
