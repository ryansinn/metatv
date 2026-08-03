"""What's New entry: assigning a category (Watch Later, Explore) no longer
reloads the whole results list and throws the user back to the top."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=274,
    title="Adding something to Watch Later no longer sends you back to the top",
    items=(
        "Sorting through a long list and adding one item to Watch Later "
        "reloaded the entire list and scrolled you back to the beginning — so "
        "every single action cost you your place.",
        "The reload existed for a different case: when the category you pick is "
        "also added to Global Exclusions (Trash), those rows genuinely have to "
        "leave the list. That still reloads, because the list really did "
        "change.",
        "A plain assignment changes nothing you can see in the row, so the list "
        "is now left exactly as it was — same scroll position, same place in "
        "the list. This matches how liking, favoriting and marking watched "
        "already behaved.",
        "Note the Watch Queue and Recommended sections can still rebuild after "
        "some actions; those are separate lists and are not covered by this "
        "change.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Scroll deep into a long results list (a few hundred rows down). "
        "Right-click an item → Watch Later. The list stays exactly where it "
        "was — same rows on screen, same scroll position.",
        "Repeat with the Explore quick-pick — same result, no jump.",
        "Now use the Trash quick-pick, which also adds the category to Global "
        "Exclusions. The list DOES reload here, and the trashed rows disappear "
        "— that reload is intentional.",
        "Confirm the assignment actually happened: reopen the item's context "
        "menu (or check the Watch Later category) and see it recorded.",
    ),
)
