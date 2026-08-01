from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=196,
    version="0.15.0",
    date="2026-08-01",
    title="Explore → from Favorites, Watch Queue and Recommended",
    items=(
        "The 'Explore →' link that used to sit only on History is now on the "
        "Favorites, Watch Queue and Recommended sidebar sections too. Each one "
        "opens the same cascading-columns view, seeded with that section's own "
        "contents as the first column — your favorites, your queue in your order, "
        "or your current recommendations — so you can walk outward from any of "
        "them instead of only from what you've already watched.",
        "Recommended's Explore shows exactly what the sidebar rail is showing "
        "(same scoring, same movie/series balance), and opening it no longer "
        "counts as a second 'shown' for those titles.",
        "Favorites and the Watch Queue are records of what you engaged with, so "
        "entries on a disabled or expired source still appear there; the columns "
        "you drill into stay filtered to your active sources, as before.",
    ),
    test_steps=(
        "Sidebar → Favorites header: an 'Explore →' link appears on the right. "
        "Click it → the full-width cascading-columns view opens, headed "
        "'★ Favorites', with your favorites as column 1 in the same order the rail "
        "shows them (recently played first, then never-watched A→Z).",
        "Sidebar → Watch Queue header: click 'Explore →' → the view opens headed "
        "'📋 Watch Queue' with your queue as column 1 in YOUR queue order (not "
        "alphabetical).",
        "Sidebar → Recommended header: click 'Explore →' → the view opens headed "
        "'🎯 Recommended' and column 1 matches the titles listed in the "
        "Recommended rail.",
        "In any of the three, click a title in column 1 → a new column of similar "
        "titles cascades to the right, and the detail strip fills in — same "
        "behaviour as History's Explore.",
        "Press Esc / click ✕ in any of them → you return to Browse and the sidebar "
        "+ details pane reopen at their previous widths (they are auto-collapsed "
        "while Explore is open). Re-open the app: the sidebar width is unchanged.",
        "Sidebar → History header: 'Explore →' still opens the Watch History view "
        "exactly as before.",
    ),
)
