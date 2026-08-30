from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=452,
    version="0.57.0",
    date="2026-08-30",
    title="Sports channels stop being sorted into the wrong league",
    items=(
        "A Green Bay local station was filed under the NBA. A French channel "
        "called TF1 was filed under Formula 1. A movie called Conflict was "
        "filed under the NFL.",
        "The app was looking for league names anywhere inside a channel name, "
        "so GREE-NBA-Y, T-F1 and co-NFL-ict all counted as matches.",
        "It now only matches whole words. 2,089 wrong league labels are gone "
        "and 273 correct ones appear that were being missed.",
        "The AHL also works now. It was already in the list of leagues but "
        "written in a way that could never match how the channels are actually "
        "named, so all 64 AHL team channels were unlabelled.",
    ),
    test_steps=(
        "Filter by NBA and confirm only basketball appears - no local network "
        "affiliates.",
        "Filter by Formula 1 and confirm TF1 is not listed.",
        "Confirm AHL team channels now carry the AHL league.",
        "Confirm NHL, Premier League and UFC channels are still labelled.",
    ),
)
