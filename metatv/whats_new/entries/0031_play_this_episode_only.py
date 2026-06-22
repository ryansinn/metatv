from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=31,
    version="0.7.7",
    date="2026-06-22",
    title="Play This Episode Only",
    items=(
        "New episode context-menu action: 'Play This Episode Only'. When "
        "'Autoplay season episodes' is enabled, right-clicking an episode shows "
        "both 'Play Episode' (queues the rest of the season as usual) and the new "
        "'Play This Episode Only' option — which plays just the selected episode "
        "without queuing any subsequent ones.",
        "This is a per-play opt-out of the autoqueue, so you can watch a single "
        "episode out of order or re-watch one episode without committing to the "
        "whole season run.",
    ),
)
