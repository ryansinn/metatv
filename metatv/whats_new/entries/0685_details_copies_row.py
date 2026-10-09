from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=685,
    version="0.131.0",
    date="2026-10-08",
    title="Every copy of a title, on one line",
    items=(
        "\"Available in\" lists the copy you are on first and the others "
        "beside it, each named by its language/region with its quality badge; "
        "copies with the same name collapse into one chip with a chooser; "
        "filtered and expired copies open into their own labelled rows; "
        "copies on a source you have turned off no longer appear at all.",
    ),
    test_steps=(
        "Select a film with several copies — 'Available in' starts with the "
        "copy you are on, highlighted, and shows 4K/UHD as a coloured badge.",
        "Click a '×2' chip — a menu lists both copies by collection; choosing "
        "one shows that copy.",
        "Click '+N filtered' — a 'Filtered' row opens below; click the "
        "'Filtered' label — it folds back; restart — the open/closed state is "
        "remembered.",
        "Turn a source off in Sources — its copies vanish from 'Available in' "
        "entirely.",
    ),
)
