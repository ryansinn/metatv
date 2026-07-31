from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=175,
    version="0.14.1",
    date="2026-07-31",
    title="Preview lightbox polish: strip-card badges, cleaner cards, clearer selected state",
    items=(
        "The 'Similar Titles' cards in the preview lightbox now show the same badges "
        "as the details-pane rows: language/region, a ★ rating, and small state icons "
        "for liked (👍), in Watch Later (📋), favorited (★), and watched (green ✓) — so "
        "you can tell at a glance what you've already engaged with.",
        "Removed the redundant ⤢ button that sat on every Similar card — the whole "
        "poster was already click-to-dive, so the extra button was just clutter. "
        "Clicking anywhere on a card still opens its preview.",
        "The watch-queue action is now labelled 'Watch Later' everywhere (menus, the "
        "lightbox, the Similar rows), matching the details pane — it used to read "
        "'Queue' in some places and 'Watch Later' in others for the same action.",
        "A selected details-rail button (rating / like / Watch Later / watchlist) now "
        "fills with the accent colour and an accent border, so ON is unmistakable — "
        "before, the selected state looked almost identical to hover.",
    ),
    test_steps=(
        "Open a title's preview lightbox (click a Similar Titles row): each card in the "
        "bottom 'Similar Titles' strip shows a language/rating meta line and — for "
        "titles you've engaged with — 👍/📋/★/✓ state icons under the poster.",
        "Confirm no Similar strip card has a small ⤢ button in its corner; clicking "
        "anywhere on a card still opens that title's preview.",
        "Right-click a channel and check the watch-queue action reads 'Add to Watch "
        "Later' / 'Remove from Watch Later' (not 'Add to Queue'); same wording in the "
        "lightbox button and the Similar-row queue tooltips.",
        "In the details pane, click a rail toggle (e.g. Like or Watch Later): the "
        "selected button shows a clear blue accent fill + border, visibly different "
        "from an unselected or merely-hovered button.",
    ),
)
