"""What's New entry for titles that kept their prefix because the parser did not
recognise a bracketed quality token."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=281,
    title="Some titles showed their raw source label instead of a clean name",
    items=(
        "Titles like \"IT-[4K] - Monty Python e il Sacro Graal\" displayed the "
        "source's whole label — language code, brackets, dashes and all — "
        "instead of just the film's name with those lifted into chips.",
        "MetaTV understood several ways a source can prefix a title (\"IT-4K\", "
        "\"4K-DE\", \"DE 4K\") but not one where the quality is in brackets. A "
        "shape it doesn't recognise isn't partly handled — it's skipped "
        "entirely, so the whole prefix stayed in the title.",
        "About 100 titles in a typical library are affected; they clean "
        "themselves up the next time the library re-scans names.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Search for a title you know came through with a bracketed prefix (e.g. "
        "\"IT-[4K] - …\"). After the next source refresh it shows just the film "
        "name, with the language and 4K as separate chips.",
        "Confirm the quality chip reads \"4K\" — not \"[4K]\".",
        "Check a title that already looked right (\"IT-4K - …\", \"4K-DE - …\") "
        "— unchanged.",
    ),
)
