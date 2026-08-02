"""What's New entry for user-defined Global Exclusions keywords."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=244,
    title="Global Exclusions: hide by your own keyword",
    items=(
        "Global Exclusions has a new Keywords section — type any word or phrase "
        "(e.g. \"wrestling\", \"telenovela\") and every channel whose title "
        "contains it is hidden everywhere: the channel list, Discover, and "
        "Recommendations. Case doesn't matter, and the list is empty by default "
        "— the app never guesses what you want hidden.",
        "This is a separate list from the Restricted Content keywords in "
        "Settings (which only affects the Adult-content filter) — the two never "
        "mix, and editing your new keyword list takes effect on the very next "
        "load, no re-scan needed.",
    ),
    version="0.22.0",
    date="2026-08-02",
    test_steps=(
        "Open Global Exclusions and add a keyword that matches several titles "
        "in your library (e.g. a genre word like \"wrestling\") → click OK.",
        "Open the channel list — every title containing that word (in any "
        "case) is gone from Browse/search results.",
        "Open Discover — a shelf/genre row that used to include a matching "
        "title no longer shows it.",
        "Open Global Exclusions again → toggle 'Pause Global Exclusions' → "
        "the hidden titles reappear everywhere; un-pause and they're hidden again.",
    ),
)
