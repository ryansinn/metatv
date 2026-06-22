from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=29,
    version="0.7.5",
    date="2026-06-22",
    title="Series Alerts",
    items=(
        "Right-click any series in the channel list and choose 'Alert me for new episodes' "
        "to start monitoring it. MetaTV checks for new episodes when it starts up and "
        "shows a toast notification when new content arrives.",
        "A 'New Episodes' section appears in the sidebar whenever there are unread "
        "alerts — click any entry to jump straight to the series.",
        "Manage your monitored series from the sidebar's 'New Episodes' header menu "
        "('Manage Alerts…') — stop monitoring individual series or clear all alerts "
        "from one place.",
    ),
)
