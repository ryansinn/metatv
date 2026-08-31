from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=462,
    version="0.59.0",
    date="2026-08-31",
    title="Similar Titles now obeys every exclusion, not two of six",
    items=(
        "Similar Titles, the lightbox lens and \"See all in Search\" applied "
        "only two of your six exclusion settings. Adult content was never "
        "filtered there at all — 215 titles your channel list hides could "
        "appear as a suggestion beside something you were watching.",
        "Also now applied there: excluded content types (114 of your titles "
        "are tagged AI-generated or AI-voiceover), your keyword exclusions, "
        "and the \"Uncategorized\" toggle.",
        "Pausing Global Exclusions still does what it always did — shows you "
        "your own filtering — but it no longer unhides adult content, which "
        "is a separate setting.",
        "Sports and Events had the same gap in a different place: their "
        "scope skipped the adult gate and the Uncategorized toggle. Nothing "
        "adult is filed under sports or events in your library today, so "
        "nothing was leaking, but the gap is closed.",
        "All six axes now come from one place, so a filter added later "
        "reaches every one of these surfaces without being wired up again.",
    ),
    test_steps=(
        ("Settings ▸ set adult content to Hide. Open a movie's details and "
         "check Similar Titles — nothing adult should appear.",
         "view:browse"),
        "Open the Similar Titles lightbox from that same title and confirm "
        "the same, then click \"See all in Search\".",
        "Add a keyword to Global Exclusions that matches a title you can see "
        "in Similar Titles. It should disappear from there too.",
        "Exclude a content type under Global Exclusions ▸ Content Provenance "
        "and confirm those titles leave Similar Titles.",
        "Pause Global Exclusions. Your own exclusions should come back — but "
        "adult content should stay hidden.",
        "Set adult content to Show and confirm it reappears in Similar "
        "Titles, so the gate follows the setting rather than always hiding.",
    ),
)
