from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=586,
    version="0.95.0",
    date="2026-09-04",
    title="Downloads land in a real library",
    items=(
        "Downloads land in a Plex/Jellyfin-readable tree with clean names "
        "built from stored metadata — a flat filename when the metadata is "
        "too thin to fill the tree, and a flat layout as a choice for "
        "everything.",
        "\"Downloaded\" now means the file actually exists on disk — the "
        "Downloaded scope and its badge check the filesystem, not a stored "
        "flag, so a file deleted outside the app drops off on the next "
        "refresh.",
        "A free-space floor stops downloads before they fill the disk, "
        "either right away or after finishing whatever is already in "
        "flight — \"finish current\" only happens when the remaining bytes "
        "truly fit, and the queue row says why otherwise.",
        "Settings ▸ Downloads gains the folder, layout and floor controls "
        "that were previously hardcoded defaults.",
    ),
    test_steps=(
        "Download a movie with a year → it lands as 'Title (Year).ext' "
        "under Movies/ in your downloads folder.",
        "Delete that file outside the app, then refresh the Downloaded "
        "scope → the title disappears (the badge/scope clears).",
        "In Settings ▸ Downloads, set the free-space floor above your "
        "actual free space and download something → the queue row explains "
        "why it stopped.",
    ),
)
