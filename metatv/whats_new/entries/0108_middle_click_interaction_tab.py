from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=108,
    version="0.9.0",
    date="2026-06-28",
    title="Configurable middle-click action + new Settings → Interaction tab",
    items=(
        "Middle-click on a channel row is now configurable. Choose what it does in "
        "Settings → Interaction → 'Middle-click action': 'Resume from saved position' "
        "(default) or 'Play with endless buffer' (disk-backed maximum buffer for "
        "unstable streams). More actions can be added over time.",
        "New 'Interaction' tab in Settings gathers the channel-row click preferences. "
        "The existing 'Default double-click action' setting moved here from the "
        "Playback tab — same behavior, clearer home.",
    ),
    test_steps=(
        "Open Settings → Interaction and confirm it contains both 'Default "
        "double-click action' and 'Middle-click action' (the double-click setting is "
        "no longer on the Playback tab).",
        "Set 'Middle-click action' to 'Play with endless buffer' and save. Middle-click "
        "a channel row and confirm it plays with the open-ended (disk-backed) buffer.",
        "Set 'Middle-click action' back to 'Resume from saved position' and save. "
        "Middle-click a partially-watched movie and confirm it resumes from the saved "
        "position.",
        "Reopen Settings → Interaction and confirm both combos restored the values you "
        "last saved (persistence round-trip).",
    ),
)
