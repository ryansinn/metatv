from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=23,
    version="0.7.4",
    date="2026-06-22",
    title="Series episode watch-state fixes and multi-select",
    items=(
        "Fixed: 'Mark as Watched' now immediately shows the ✓ check on the episode "
        "row. Previously the context-menu label flipped but the row icon stayed ▶ "
        "because only is_watched was written — the icon reads watch_completed and "
        "watch_percent. All three fields are now set coherently in a single commit.",
        "Fixed: watched ✓ icons persist after app restart. The previous code never "
        "wrote watch_completed to the database for manual marks, so every reload "
        "showed ▶ for manually-marked episodes.",
        "Fixed: marking an episode no longer collapses all seasons and resets the "
        "scroll position. The icon is now updated in-place on the single affected "
        "row — the tree is not rebuilt.",
        "Season nodes now show a ✓ (all episodes complete) or ◐ (some complete) "
        "indicator derived from their episodes — no new database column required.",
        "Multi-select: hold Shift or Ctrl to select multiple episodes, then "
        "right-click to mark them all as Watched/Unwatched in one action.",
        "Season context menu: 'Mark Season as Watched' / 'Mark Season as Unwatched' "
        "sets all episodes in the season at once.",
    ),
)
