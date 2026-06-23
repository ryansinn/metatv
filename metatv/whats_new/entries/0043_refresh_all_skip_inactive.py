from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=43,
    version="0.9.0",
    date="2026-06-23",
    title="Skip inactive sources on Refresh All",
    items=(
        (
            "New setting in Settings → Interface → Sources:"
            " 'Refresh inactive sources when refreshing all'."
            " Turn it off to make Refresh All skip sources you've disabled —"
            " no more waiting through a 20-minute tagging pass on a source you're not using."
        ),
        (
            "Refreshing a single source from its refresh button always works regardless"
            " of this setting — that's a deliberate user action."
        ),
        "Default is on (previous behaviour preserved for existing users).",
    ),
)
