from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=213,
    version="0.18.0",
    date="2026-08-01",
    title="Fresh installs no longer replay the entire changelog",
    items=(
        "On a brand-new config (first launch on a machine, or a wiped config "
        "folder), the What's New dialog used to open with every historical "
        "entry — hundreds of panels. A fresh install now starts quietly: the "
        "dialog only appears after your first upgrade, showing just what "
        "changed since. Help ▸ What's New still lets you browse everything "
        "anytime.",
    ),
    test_steps=(
        "Back up and remove ~/.config/metatv (or point HOME at a temp dir), "
        "launch the app → NO What's New dialog appears on first launch.",
        "Quit; confirm config.yaml now has last_seen_whats_new_id set to the "
        "newest entry id (not 0).",
        "Help ▸ What's New → the full changelog still opens on demand.",
        "On your REAL config (upgrade path), launch after this update → the "
        "dialog still shows only the new 0.18.0 entries.",
    ),
)
