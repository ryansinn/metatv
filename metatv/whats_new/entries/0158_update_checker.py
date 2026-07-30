from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=158,
    version="0.10.0",
    date="2026-07-30",
    title="Automatic update checks",
    items=(
        "MetaTV can now check GitHub for a newer release and let you know when "
        "one is available, with a one-click assisted download.",
        "When an update is found you get a non-modal banner: Download saves the "
        "new build to your Downloads folder and opens it so you can drag MetaTV "
        "into Applications; \"Skip this version\" stops the reminder for that "
        "release; \"Later\" just dismisses it.",
        "A new \"Automatically check for updates\" toggle and a \"Check for "
        "updates now\" button live in Settings → Interface → Updates. Automatic "
        "checks run at most once a day and only in the packaged app — running "
        "from source is never auto-checked.",
    ),
    test_steps=(
        "Open Settings → Interface: the Updates group shows an \"Automatically "
        "check for updates\" checkbox (on by default) and a \"Check for updates "
        "now\" button.",
        ("Click \"Check for updates now\": a \"Checking for updates…\" toast "
         "appears, then either an \"update available\" banner (if a newer "
         "release exists) or a \"You're up to date\" / \"Couldn't check\" toast.",
         "settings:interface"),
        "With an update banner showing, click \"Skip this version\": a "
        "confirming toast appears and that version no longer prompts on startup "
        "(update_skip_version is saved).",
        "Toggle \"Automatically check for updates\" off and click OK, reopen "
        "Settings → Interface: the checkbox stays off (persisted to config).",
    ),
)
