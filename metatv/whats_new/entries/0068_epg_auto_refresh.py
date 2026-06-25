from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=68,
    version="0.9.0",
    date="2026-06-24",
    title="Self-tuning Auto EPG refresh + periodic scheduler + legible progress",
    items=(
        "EPG now refreshes automatically on a schedule — no need to open the "
        "EPG view to trigger a fetch. A 1-hour background timer pokes the "
        "per-provider interval check, and an initial poke fires 2 seconds after "
        "launch so the app honors the configured interval from the moment it starts.",
        "The default refresh interval is now 'Auto (recommended)': it self-tunes "
        "by fetching at half the guide's depth, clamped to 6 hours – 7 days. A "
        "2-day feed refreshes roughly every 1 day; a 7-day feed every 3.5 days. "
        "The provider editor's Guide freshness line shows the feed depth and the "
        "resolved interval, so Auto is never an opaque black box.",
        "The EPG refresh progress panel now animates during the download, channel-"
        "matching, and guide-clearing phases (indeterminate / marquee bar) and "
        "switches to a determinate percentage bar only during the bulk-save phase "
        "where progress can actually be measured. Phase labels tell you exactly "
        "what is happening: 'Downloading guide…', 'Matching channels to your "
        "streams…', 'Clearing old guide…', then 'Saving N/Total (%)…'.",
    ),
    test_steps=(
        "Open Settings → EPG tab and confirm the global refresh interval shows "
        "'Auto (recommended)' selected by default.",
        "Open a provider editor and confirm the Guide freshness line (when data "
        "has been fetched) shows a depth and resolved interval, e.g. "
        "'Current — guide through 26 Jun 2026 · Auto: ~7-day feed → refreshing "
        "~every 3d'.",
        "Set a provider's refresh interval to 'Auto (recommended)' in the "
        "provider editor, save, wait for a scheduled refresh (or trigger one with "
        "'Refresh EPG now'), and confirm the status line updates with the correct "
        "depth and resolved interval.",
        "Trigger an EPG refresh (via 'Refresh EPG now' in the provider editor) "
        "and watch the bottom-right progress panel: confirm it animates "
        "(marquee/busy bar) during 'Downloading guide…', 'Matching channels to "
        "your streams…', and 'Clearing old guide…', then switches to a filling "
        "percentage bar during 'Saving…'.",
        "Leave the app running for over an hour with EPG auto-refresh enabled "
        "and confirm an EPG refresh fires automatically without needing to open "
        "the EPG view.",
    ),
)
