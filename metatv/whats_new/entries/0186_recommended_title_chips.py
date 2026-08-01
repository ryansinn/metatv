from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=186,
    version="0.15.0",
    date="2026-07-31",
    title="Recommended rows: the title is the title — facets are chips",
    items=(
        "Recommendation rows now read as 'Title · Year' with the language and "
        "quality shown as small, right-aligned chips, instead of cramming region "
        "and quality into the title text at the same size as the name.",
        "The language chip now shows the title's actual audio language (e.g. EN) — "
        "not the source region. A German-sourced English title used to show a "
        "misleading [DE] in the row even though the recommended version is English; "
        "it now correctly reads [EN] (region lives in the details pane).",
        "Polish: short titles are no longer chopped ('1983' used to render as '1…3'); "
        "the year is now a subtle bordered chip; and the language chip is always the "
        "far-right element, so the right edge stays aligned across rows.",
    ),
    test_steps=(
        "Open the sidebar 'Recommended' section: each row shows the title and year "
        "on the left, with language/quality as small chips pushed to the far right "
        "— no region code jammed into the title text.",
        "Find an English title sourced from a non-English region (e.g. a 'EN - …' "
        "movie): its chip reads the language (EN), not the source region, and no "
        "stray region code appears in the title.",
        "Find a short title (e.g. '1983', 'Danger Mouse'): it shows in FULL, not "
        "chopped mid-word — only a genuinely-too-long title truncates in the middle.",
        "Scan the right edge of the list: the language chip lines up as the last "
        "element on every row, even on rows that also carry a 4K/quality chip (the "
        "quality chip sits just after the year, on the left).",
        "Confirm the row still selects on click, opens on double-click, and shows "
        "its context menu on right-click (the chips don't swallow those).",
    ),
)
