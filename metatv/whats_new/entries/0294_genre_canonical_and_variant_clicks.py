"""What's New entry: details pane showed raw provider genre wording; filtered
variant chips were not clickable."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=294,
    title="Genres read the same everywhere, and filtered variants are clickable",
    items=(
        "The details pane was showing genres in whatever language the provider "
        "sent — \"Dramma\" on an Italian source, \"Drame / Mystère / "
        "Science-Fiction & Fantastique\" on a French one — while the results "
        "row for the very same title said \"Drama\". One fact, two answers, "
        "both on screen at once.",
        "The pane now uses the same curated mapping everything else uses (360 "
        "aliases across 38 canonical genres), so a title reads identically "
        "wherever you meet it, and clicking a genre chip filters correctly "
        "instead of searching for a word the filters never produce.",
        "Nothing was lost and nothing is destroyed: the provider's own wording "
        "is still stored exactly as it arrived. Only the display is "
        "canonicalised — when the app speaks other languages, genres will be "
        "shown in yours.",
        "Filtered Variants: the chips can now be clicked to switch to that "
        "version. They previously had a right-click menu only, so a left click "
        "silently did nothing — and they were dim enough to look disabled, "
        "which they never were. They stay quieter than active versions, but "
        "they now look and behave like the links they are.",
    ),
    version="0.26.0",
    date="2026-08-04",
    test_steps=(
        "Find a title from a non-English source (Italian, French, Polish) and "
        "open its details. The genre chips read in English — \"Drama\", not "
        "\"Dramma\" or \"Drame\".",
        "Compare against the same title's row in the results list: the genre "
        "shown there and in the details pane now match.",
        "Click a genre chip. The list filters to that genre and returns "
        "results (previously a localised value matched nothing).",
        "Open a title that has several versions and expand \"FILTERED "
        "VARIANTS\".",
        "Left-click one of the greyed chips — the pane switches to that "
        "version. Previously nothing happened.",
        "Hover a filtered chip: it brightens and the cursor becomes a hand.",
        "Right-click one — the manage menu still appears as before.",
        "A struck-through (hidden-category) chip is still struck through, and "
        "is also clickable.",
    ),
)
