from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=182,
    version="0.15.0",
    date="2026-07-31",
    title="Recommendations now respect your Global Filter exclusions",
    items=(
        "The Recommended section in the sidebar now honors the same exclusions you "
        "set everywhere else. If you've blocked a language or category — either by "
        "excluding it in the Global Filter or with a 'Block [PREFIX]' quick action "
        "(e.g. DE, PL) — those titles no longer show up in your recommendations.",
        "Previously Recommendations applied only the category blacklist and quietly "
        "ignored the per-language 'Block [PREFIX]' codes, so blocked languages could "
        "still slip into the list. Recommendations, Discover and Similar Titles now "
        "all resolve exclusions through one shared, pause-aware path, so they can't "
        "drift apart.",
        "Pausing the Global Filter still brings everything back, and the Continue "
        "Watching / Queue history is unaffected — those are record views of things "
        "you've already engaged with, so they intentionally still show excluded "
        "sources.",
    ),
    test_steps=(
        "In the Global Filter, exclude a language you actually have recommendations "
        "for (or use a title's 'Block [PREFIX]' quick action, e.g. DE) → open the "
        "sidebar 'Recommended' section and confirm no items of that language appear.",
        "Pause the Global Filter → refresh Recommended → the previously-excluded "
        "language reappears in the list.",
        "Un-pause / re-block, then check the Watch Queue 'Continue Watching': items "
        "you've already started in that language still appear there (record view — "
        "exempt from the soft exclusions).",
    ),
)
