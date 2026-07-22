from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=149,
    version="0.10.0",
    date="2026-07-22",
    title="Migration toast no longer clips a second progress row",
    items=(
        "The \"Migration in progress\" toast now grows to fit every running "
        "migration. Previously the panel kept its one-row height even when a "
        "second migration started — both rows got squeezed into that height, "
        "with the labels clipped to about half their text and the second "
        "row's bar squeezed against the frame edge. This first became visible "
        "when two migrations ran back-to-back on launch (detected_title_reparse "
        "v5 + tag_backfill v8), but the underlying sizing bug was pre-existing "
        "and would have hit any future multi-migration launch.",
        "The panel now measures its own content directly instead of trusting "
        "a nested layout's size hint, so it reliably grows one full row per "
        "concurrent migration (and stays put once tasks are running — the "
        "one-row case already worked correctly).",
    ),
    test_steps=(
        "Trigger two background migrations on launch (e.g. bump two migration "
        "versions so both need to run) and watch the corner toast: each row's "
        "label is fully readable (not cut off), and the panel visibly grows "
        "taller for the second row rather than squeezing both into the same "
        "one-row height.",
        "With only one migration pending, confirm the toast still looks the "
        "same as before (single full-height row, no regression).",
    ),
)
