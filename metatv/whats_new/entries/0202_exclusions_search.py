from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=202,
    version="0.16.0",
    date="2026-08-01",
    title="Search box in Global Exclusions",
    items=(
        "The Global Exclusions dialog now has a search box at the top of the "
        "exclusion list — type a prefix code, a language, or a region and the "
        "list narrows in realtime as you type.",
        "Matches both the short code (e.g. 'FR') and its human-readable name — "
        "typing 'french' finds the French language group (and its FR member), "
        "typing 'germany' finds the German group via its DE entry.",
        "Every section filters together — Languages, Platforms, Content Types, "
        "Content Provenance and User Categories — and a type's heading hides "
        "once nothing under it matches, so you're never staring at an empty "
        "'Languages' label.",
        "No matches shows a small 'No exclusions match' message instead of a "
        "blank list. Clearing the box restores everything, including which "
        "groups were expanded before you started typing.",
    ),
    test_steps=(
        "Open Global Exclusions and type 'french' in the new search box: the "
        "French group expands and shows FR, other language groups (e.g. "
        "German) hide, and the Languages heading stays visible.",
        "Type 'germany': the German group shows (matching DE's full name "
        "'Germany') even though the group itself is named 'German'.",
        "Clear the search box: the full list returns, including any groups "
        "that were expanded before you searched.",
        "Type a nonsense query (e.g. 'zzzznotreal'): every group hides and a "
        "muted 'No exclusions match' message appears in the list.",
    ),
)
