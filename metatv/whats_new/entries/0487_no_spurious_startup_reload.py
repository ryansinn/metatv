from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=487,
    version="0.64.0",
    date="2026-09-01",
    title="The list reloading itself for no reason",
    items=(
        "Shortly after launch the channel list would empty and repopulate on "
        "its own, without anyone touching anything — and come back with "
        "exactly the same rows.",
        "The filter sidebar's Language, Region, Genre and other sections are "
        "filled by a background count that takes a while on a large library. "
        "Until it lands those sections are empty, so a saved filter cannot be "
        "applied — and the list was reloaded once it arrived, always.",
        "Now it only reloads when your saved filters would actually narrow "
        "the results. If nothing is deselected there is nothing to re-apply, "
        "so the list is left alone.",
    ),
    test_steps=(
        ("Launch with no filters deselected and watch the channel list for a "
         "minute: it must not blank and reload on its own.", "view:list"),
        ("Deselect a language, quit, relaunch — the list must end up narrowed "
         "to your saved selection.", "view:browse"),
        "Hide 'Untagged' in one facet, relaunch, and confirm those rows stay "
        "hidden after startup finishes.",
    ),
)
