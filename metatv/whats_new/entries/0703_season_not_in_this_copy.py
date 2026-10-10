from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=703,
    version="0.143.0",
    date="2026-10-09",
    title="Seasons a copy doesn't have — and where they are",
    items=(
        "When a source lists a season but ships none of its episodes, the series "
        "tree says 'Season 1 · not in this copy' and, under it, lists your other "
        "copies of the series with what each is known to hold. Double-click one to "
        "switch to that copy — nothing switches on its own.",
    ),
    test_steps=(
        "Open '4K-SC - Invasion (2021)' — Seasons 1 and 2 read '· not in this copy' "
        "(muted); expand one — rows like '↪ Open the English (EN) copy · TREX Shared — "
        "not checked yet' are listed.",
        "Hover a row — the tooltip says it is a different version and that double-click "
        "switches the tree to it.",
        "Double-click it — the tree switches to that copy and the status bar says so; "
        "come back to Invasion 4K-SC — that row now shows 'has 10 episodes'.",
    ),
)
