from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=163,
    version="0.11.0",
    date="2026-07-30",
    title="Similar Titles no longer suggests content from disabled or expired sources",
    items=(
        "The \"Similar Titles\" suggestions on a title's details pane — and the "
        "similar-titles preview lightbox — now hide anything that lives only on a "
        "source you've switched off or that has expired, matching the rest of the app.",
        "Previously a look-alike from a disabled or expired source could still show "
        "up as a suggestion (and open, only to fail to play). Both suggestion "
        "surfaces now run through one shared, source-aware query.",
    ),
    test_steps=(
        "Have at least two sources where the same or a similar title exists on both. "
        "Disable one source (or use one whose subscription has expired). Open a title "
        "on an ACTIVE source and scroll to \"Similar Titles\": no suggestion should come "
        "from the disabled/expired source — only active-source titles appear.",
        "Right-click a Similar Titles row to open the preview lightbox and read its "
        "own \"Similar Titles\" mini-list: it likewise contains no entries from the "
        "disabled/expired source.",
        "Re-enable the source, reopen the same title, and confirm its similar titles "
        "come back into the suggestions — the gate only hides inactive/expired sources.",
    ),
)
