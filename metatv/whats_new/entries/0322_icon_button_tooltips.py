"""What's New entry: icon-only buttons that offered no explanation now have
tooltips, and collapse toggles keep theirs truthful as they flip."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=322,
    title="Buttons that were just a symbol now say what they do",
    items=(
        "Several controls were nothing but a glyph, with no tooltip and no "
        "other explanation: the collapse arrows on the details pane's Plot, "
        "Cast & Crew and Tags sections, the group expander in the filter "
        "panel, the ✕ that dismisses a notification, and the two reorder "
        "arrows in the source editor's URL list.",
        "The URL arrows matter most of the four: that list's order IS the "
        "order hosts are tried, so the arrows change failover priority — "
        "something the arrow shape alone never said. Their tooltips now say "
        "it.",
        "The collapse toggles set their tooltip where they flip their arrow, "
        "so it always matches what the arrow is currently offering rather "
        "than being right half the time.",
    ),
    version="0.32.0",
    date="2026-08-22",
    test_steps=(
        "Open a movie's details pane and hover the small arrow beside Plot, "
        "Cast & Crew or Tags — it reads \"Collapse this section\"; click to "
        "collapse and hover again — it now reads \"Expand this section\".",
        "Open the filter panel and hover the arrow beside a group name — it "
        "explains that it shows the codes in that group, and flips wording "
        "once expanded.",
        "Trigger any notification and hover its ✕ — \"Dismiss this "
        "notification\".",
        "Open a source for editing, go to its URL list, and hover the up/down "
        "arrows on a row — they explain that the order sets which URL is "
        "tried first.",
    ),
)
