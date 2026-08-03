"""Channel list horizontal scrollbar fix."""

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=258,
    version="0.24.0",
    title="Channel list layout fix",
    items=(
        "Fixed a layout issue where the channel list incorrectly showed a horizontal scrollbar on first launch, clipping the right-hand language chips and details pane.",
    ),
    test_steps=(
        "Launch the app and verify that the channel list shows no horizontal scrollbar — all channel names, language chips, and collection chips are fully visible without any right-side clipping.",
    ),
)
