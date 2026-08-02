from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=242,
    version="0.21.0",
    date="2026-08-02",
    title="Sources manager: readable source names + a tabbed editor",
    items=(
        "The Sources manager's left column no longer crowds five icon buttons "
        "onto each row, which was truncating provider names — rows now show "
        "just the status dot, full name, and expiry state. Refresh, Analyze, "
        "Refresh Guide, and Enable/Disable moved into the detail pane as a "
        "labelled action bar under the provider name.",
        "The detail pane is now three tabs — Summary (name, status, Account "
        "Info, the action bar), Connection (Credentials, DNS/URLs), and "
        "Settings (auto-refresh, EPG controls, adult-content flag) — instead "
        "of one long scroll. The last-opened tab is remembered.",
        "Delete / Test Connection / Discard / Save Changes now live in a "
        "persistent footer below the tabs, visible no matter which tab is "
        "open, with Delete kept visually separated from Save so a destructive "
        "click never sits next to a save click.",
        "The old '← Done Editing Sources' bar is gone — click the sidebar "
        "Sources strip again to close the manager and return to the channel "
        "list, the same way the other view chips toggle.",
    ),
    test_steps=(
        "Click the sidebar Sources strip to open the manager → left-column "
        "rows show only a status dot and the full provider name (no icon "
        "buttons, no truncation) → click the strip again → the manager closes "
        "and the channel list returns.",
        "Select a source → Summary tab shows the name, a small status dot, "
        "Enabled checkbox, action bar (Refresh / Analyze / Refresh Guide / "
        "Disable), and Account Info → click Connection tab → Credentials + "
        "DNS/URLs list appear → click Settings tab → auto-refresh, EPG "
        "controls, and the adult-content flag appear (no Delete button here).",
        "From any tab, confirm Delete / Test Connection / Discard / Save "
        "Changes are all visible in the footer → click Disable in the action "
        "bar → the button shows a brief spinner then relabels to Enable.",
        "Switch to the Connection tab, reopen the app (or reselect the "
        "source) → the editor reopens on the Connection tab.",
    ),
)
