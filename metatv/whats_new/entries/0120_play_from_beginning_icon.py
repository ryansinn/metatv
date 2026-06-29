from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=120,
    version="0.9.0",
    date="2026-06-28",
    title="'Play from Beginning' shows a play triangle, not a box",
    items=(
        "In a channel's right-click menu, the 'Play from Beginning' option now shows "
        "the gray play triangle (▶) — the same clean glyph as plain Play — instead of "
        "the ⏮ last-track symbol, which rendered as an empty gray box in many fonts.",
        "It reads distinctly from the resumable default Play by COLOUR: the default "
        "'Play from M:SS' is orange (it resumes), while 'Play from Beginning' is gray "
        "(it starts over), with the labels making the difference explicit.",
        "Tidy-up: in 'start from the beginning' mode the redundant 'Play from "
        "Beginning' entry no longer appears (the default Play already starts at the "
        "beginning there); the 'Resume from …' override still appears as before.",
    ),
    test_steps=(
        "With the default 'resume' playback mode, right-click a movie you've partly "
        "watched: the menu shows an orange 'Play from M:SS' AND a gray 'Play from "
        "Beginning'.",
        "Confirm 'Play from Beginning' is a gray PLAY TRIANGLE (▶) — not an empty gray "
        "box/square — matching the plain 'Play' triangle.",
        "Right-click an UNWATCHED movie (no resume): plain 'Play' shows the same gray "
        "▶ — unchanged.",
        "Switch playback mode to 'start from the beginning' (Settings), then right-"
        "click a partly-watched movie: there is NO 'Play from Beginning' entry (it'd "
        "be redundant), but an orange 'Resume from M:SS' override IS present.",
    ),
)
