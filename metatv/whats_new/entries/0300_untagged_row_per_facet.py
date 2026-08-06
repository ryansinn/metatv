"""What's New entry: every filter section now shows how much of the library it
cannot describe, and lets you exclude it deliberately."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=300,
    title="Every filter section now tells you what it can't describe",
    items=(
        "Each facet section has an \"Untagged — N\" row at the bottom, below "
        "its values and separated from them. N is how many titles carry no "
        "value at all on that facet — the number that explains why unticking "
        "something changed the results less (or more) than you expected.",
        "It is checked by default, which is the inclusive behaviour: a filter "
        "does not hide what its facet has nothing to say about. Unticking it "
        "restores the strict form for that ONE facet — only titles carrying a "
        "value you ticked — without touching any other section.",
        "The count is a property of the data, not of your selection, so it "
        "does not move as you tick and untick values. It respects your Global "
        "Exclusions and disabled sources, so it describes the same population "
        "the value counts do.",
        "This replaces the old \"Unknown\" section. That section covered 2 of "
        "9 facets — both of them legacy axes, neither an actual tag facet — "
        "and displayed a hardcoded count of 0 for both, so it had been "
        "reporting nothing for some time. The rows are now generated from the "
        "same map the filter itself uses, so their coverage can't drift from "
        "it again.",
        "Your previous Unknown selections do not carry over; every facet "
        "starts inclusive. Switch off the ones you want strict.",
    ),
    version="0.27.0",
    date="2026-08-05",
    test_steps=(
        "Open the filter panel and expand SUBTITLE LANGUAGE. Below the "
        "languages, after a divider, there is an \"Untagged\" row with a large "
        "count and no \"only\" button.",
        "Untick one subtitle language and watch the Untagged count — it must "
        "NOT change. It describes the data, not your selection.",
        "Untick the Untagged row itself. The result list should collapse to "
        "roughly the sum of the ticked language counts — that is the old "
        "strict behaviour, now opt-in.",
        "Re-tick it; the results come back.",
        "Untick Untagged in SUBTITLE LANGUAGE only, then check GENRE — its "
        "Untagged row is still ticked. The setting is per-facet.",
        "Restart the app. The facet you switched off is still off; every other "
        "one is still on.",
        "Confirm the old \"Unknown\" section is gone from the bottom of the "
        "panel.",
        "Use \"Clear\" then \"All\" at the top of the panel — the Untagged rows "
        "follow along with everything else.",
        "Collapse and expand a section; the Untagged row stays at the bottom, "
        "below the values, in every section that has one.",
    ),
)
