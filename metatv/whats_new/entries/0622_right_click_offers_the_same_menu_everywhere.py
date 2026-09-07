from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=622,
    version="0.101.0",
    date="2026-09-07",
    title="Right-click offers the same menu everywhere",
    items=(
        "Recommended rows (Preferences dashboard and the sidebar rail) drop the "
        "two-item \"Show N versions separately\" mini-menu — right-click opens the "
        "full menu, with \"Show N versions separately\" listed first.",
        "The details pane's \"Also Available\" version chips, the Watch Alerts "
        "sidebar's monitored-series rows, and the Watch Queue's Alerts-Matched "
        "series rows now build their right-click menus the same way every other "
        "channel menu does, so a new menu action reaches them automatically.",
        "The Watch Alerts sidebar's keyword-rule menu gains \"View matches\", "
        "matching the same action already on other alert surfaces.",
        "Fixed: right-clicking a series on any surface that offers \"Browse the "
        "series\" (channel list, History, Favorites, Watch Queue, Recommended) "
        "could fail silently — the action's label was never actually callable.",
    ),
    test_steps=(
        "Right-click a Recommended row (sidebar or Preferences dashboard) → the "
        "full menu opens with \"Show N versions separately\" first (no \"More "
        "options…\").",
        "Right-click a version chip in the details pane's \"Also Available\" "
        "row → header names the version, then Play/Show details/… in the same "
        "order as before.",
        "Right-click a monitored series in the Watch Alerts sidebar → Open "
        "series / Mark seen / Stop alerts / Manage… all work.",
        "Right-click a series in the Watch Queue's Alerts-Matched group → "
        "Open series / Mark seen both work.",
    ),
)
