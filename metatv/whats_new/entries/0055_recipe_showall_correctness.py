from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=55,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe 'Show all' — clean titles, working filter, all media types",
    items=(
        "Show-All card titles are now clean: provider prefixes like '|EN|', "
        "'|MULTI|', '(US)', and '(DUAL URDU/ENG)' are stripped, matching "
        "what Search and Discover already showed.",
        "Typing in the Show-All filter now narrows results as you scroll — "
        "previously new pages loaded below the visible area ignored the filter "
        "and showed everything alphabetically.",
        "Movies and live channels now appear in Show-All alongside series when "
        "a recipe's selected tags apply to them (e.g. language or region tags). "
        "Genre-only recipes may still show only series — this is a data reality: "
        "genre tags in the current library are assigned to series only.",
    ),
    test_steps=(
        "Open the Recipe chip → add a Language or Region tag → click 'Show all' → "
        "verify card titles are clean (no '|EN|', '|MULTI|', '(US)' prefixes).",
        "In Show-All, type a word (e.g. 'days') in the filter box → verify the "
        "visible cards narrow to matches; scroll to the bottom → new pages loaded "
        "also show only matching titles, not everything alphabetically.",
        "Clear the filter box → the full result set restores and scrolling loads "
        "more unfiltered pages.",
        "Add a Language or Region ingredient → Show All → confirm movies and/or "
        "live channels appear alongside series (or note if the recipe's tag only "
        "applies to series in your library).",
    ),
)
