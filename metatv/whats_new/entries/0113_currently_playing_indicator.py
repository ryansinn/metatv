from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=113,
    version="0.9.0",
    date="2026-06-28",
    title="\"Currently playing\" indicator on the details Play button",
    items=(
        "When the title open in the details pane is the one actively playing, its "
        "Play button now lights up with a GREEN outline and a LIVE elapsed timer "
        "(e.g. \"▶ 12:34\") that counts up as playback progresses — so you can tell "
        "at a glance that what you're looking at is what's on screen.",
        "The indicator clears automatically when playback stops, or when you switch "
        "the details pane to a different title; switch back to the playing one and it "
        "lights up again.",
        "Colourblind-safe by design: the running timer is the real cue (it works "
        "without colour); the green is only reinforcement. Green is the reserved "
        "\"active / now\" accent.",
    ),
    test_steps=(
        "Open a movie in the details pane and click Play. Once it's playing, the "
        "details Play button gains a green outline and its label changes to \"▶ M:SS\" "
        "that ticks up about once a second.",
        "While it's still playing, open a DIFFERENT title in the details pane: the "
        "green outline + timer are gone (normal \"▶ Play\"). Switch back to the playing "
        "title: the green timer returns.",
        "Stop playback (close the player): within a couple of seconds the details Play "
        "button reverts to its normal \"▶ Play\" appearance.",
    ),
)
