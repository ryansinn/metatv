from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=186,
    version="0.15.0",
    date="2026-07-31",
    title="Recommended rows: the title is the title — facets are chips",
    items=(
        "Recommendation rows now read as a clean title with the quality (4K) chip "
        "beside it and the year + language as small right-aligned chips, instead of "
        "cramming region and quality into the title text at the same size as the name.",
        "The language chip now shows the title's actual audio language (e.g. EN) — "
        "not the source region. A German-sourced English title used to show a "
        "misleading [DE] in the row even though the recommended version is English; "
        "it now correctly reads [EN] (region lives in the details pane).",
        "Polish: short titles are no longer chopped ('1983' used to render as '1…3'); "
        "the quality (4K) chip now hugs the title text; the year is a subtle bordered "
        "chip; and the language chip is always the far-right element, so the right edge "
        "stays aligned across rows.",
    ),
    test_steps=(
        "Open the sidebar 'Recommended' section: each row shows the title on the left "
        "with the 4K/quality chip right after it, and the year + language chips as a "
        "right-aligned cluster — no region code jammed into the title text.",
        "Find an English title sourced from a non-English region (e.g. a 'EN - …' "
        "movie): its chip reads the language (EN), not the source region, and no "
        "stray region code appears in the title.",
        "Find a short title (e.g. '1983', 'Danger Mouse'): it shows in FULL, not "
        "chopped mid-word — only a genuinely-too-long title truncates in the middle.",
        "On a 4K title, confirm the 4K chip sits immediately after the title text, "
        "while the language chip is still the last element on the right edge (year "
        "just before it) — the right edge stays aligned across rows.",
        "Confirm the row still selects on click, opens on double-click, and shows "
        "its context menu on right-click (the chips don't swallow those).",
    ),
)
