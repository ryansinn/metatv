from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=794,
    version="0.230.0",
    date="2026-11-01",
    title="Exclude a collection from its right-click menu",
    items=("Right-click a channel in the list or search results and choose \"Exclude collection\" to hide "
           "everything that source files under it. When a title sits in several collections you pick "
           "which one, with its channel count.",
           "Right-click the collection chip in the details pane for the same, or to include it again.",
           "Excluded collections are listed in Global Exclusions; uncheck one to bring it back. Excluding "
           "applies to that source only, so the same collection name on another source stays.",
           "The \"Available in\" chip menu has one \"Exclude all … content\" row instead of two rows that did "
           "the same thing.",),
    test_steps=("Search \"espn play\", right-click an AU| ESPN PLAY PPV row — \"Exclude collection…\" lists "
                "\"Au Espn Play\" and \"Espn Play\" with counts; pick \"Au Espn Play\" — the AU rows disappear "
                "and a notice offers Undo.",
                "Open a US| ESPN PLAY channel's details — still visible; right-click its collection chip — "
                "\"Exclude the … collection\" and \"Manage Global Exclusions…\".",
                "Open Global Exclusions — Collections lists \"Au Espn Play · TREX Shared\" checked; uncheck, OK "
                "— the AU rows return.",
                "Right-click an \"Available in\" chip — a single \"Exclude all … content\" row.",),
)
