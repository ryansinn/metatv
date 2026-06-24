from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=57,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe: cross-source series collapse + Show-All filter persistence (QA 10bc0a7)",
    items=(
        "Series from different providers that label the same show with inconsistent years "
        "(e.g. '3 Body Problem 4K (2024)' vs '|ES| 3 Body Problem') now collapse into a "
        "single card in Recipe and Discover browse views — year is omitted from the "
        "content key for series and live channels since providers encode it inconsistently.",
        "Movie keys continue to use the start year (e.g. '2015-2018' → '2015') to "
        "correctly distinguish remakes from originals.",
        "Typing in the Show-All filter box now correctly filters all pages — including "
        "lazy-loaded pages on scroll — so unfiltered cards no longer appear below the "
        "first filtered page.",
    ),
    test_steps=(
        "Open the Recipe view (✦ chip). Select a broad recipe with many series results "
        "(e.g. Genre = Drama). Click 'Show all →'. "
        "Verify that cross-source series variants (e.g. '3 Body Problem' from multiple "
        "providers) appear as ONE card with a ×N badge, not as separate cards.",

        "While on the Show-All page, type a word into the filter box (e.g. 'dark'). "
        "Scroll to the bottom of the filtered results. "
        "Verify that ALL visible cards match the filter — no unfiltered cards appear "
        "below the first page of results.",

        "Clear the filter box on the Show-All page. Verify the full unfiltered result "
        "set reloads correctly and scrolling loads more unfiltered pages.",
    ),
)
