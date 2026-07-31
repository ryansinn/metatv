from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=170,
    version="0.13.0",
    date="2026-07-31",
    title="Similar Titles lightbox: carousel posters + a readable Other Versions list",
    items=(
        "The 'Similar Titles' carousel at the bottom of the preview lightbox now "
        "shows each title's poster — it was reading an empty field before, so the "
        "cards came up blank. Posters now come from your provider's own artwork.",
        "'Other Versions' is now a tidy vertical list of friendly entries: each shows "
        "its source and quality/language (e.g. 'My IPTV · 4K') instead of a cryptic "
        "two-character chip. The list is sized to the poster and scrolls when long.",
        "Removed two unnecessary lines from the lightbox — the 'Player embeds here "
        "later' placeholder under the poster and the 'disabled & expired sources "
        "excluded' note above Similar Titles.",
    ),
    test_steps=(
        "Open a title's preview lightbox (click a Similar Titles row): the bottom "
        "'Similar Titles' carousel cards show posters, not blank boxes.",
        "On a title that exists on multiple sources/qualities, check 'Other Versions' "
        "(top-right): it is a vertical, scrollable list of 'Source · Quality' rows "
        "(e.g. 'My IPTV · 4K'), each with a source-coloured left edge — no 2-char chips.",
        "Confirm there is NO 'Player embeds here later' line under the poster and NO "
        "'disabled & expired sources excluded' note above Similar Titles.",
    ),
)
