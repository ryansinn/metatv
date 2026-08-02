from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=224,
    version="0.18.2",
    date="2026-08-01",
    title="Details pane: stale '. ' titles no longer shown",
    items=(
        "The details header could still show an old '. Title' form cached in "
        "the metadata store from before the title cleanup, even though lists "
        "showed the clean name. The pane now recognizes that leading-residue "
        "form as stale and displays the clean title.",
    ),
    test_steps=(
        "Select the previously affected title (e.g. SpiderMan: Far from Home "
        "on MULTI) → the details header shows it WITHOUT the leading '. ', "
        "matching the sidebar/list rows.",
    ),
)
