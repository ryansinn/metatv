from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=433,
    version="0.54.0",
    date="2026-08-29",
    title="Liking a drama now finds dramas in every language",
    items=(
        "Recommendations keyed your taste on the exact genre spelling, so a "
        "French Drame, a Polish Dramat and an Arabic دراما each counted as a "
        "different genre from Drama - and scored zero against it.",
        "In this library 743 genre names were really 394 genres. 66,206 of "
        "231,814 genre mentions (28.6%) sat on a spelling the recommender "
        "could not match.",
        "Drama was the worst affected: 51,226 English, and another 19,463 "
        "under three other spellings that scored nothing.",
        "Genre muting had the same blind spot. A genre you muted before this "
        "release stays muted, whichever spelling it was stored under.",
        "A title tagged with two spellings of one genre counts once, not twice.",
    ),
    test_steps=(
        "Like a movie whose genre reads Drama, then open Recommendations and "
        "confirm French or German dramas now appear among the suggestions.",
        "Check the reason text under a recommendation names the genre once, "
        "not twice, for a title carrying two spellings.",
        "Mute a genre in preferences and confirm titles using that genre's "
        "other-language names disappear too.",
        "Confirm an unusual genre nobody has curated is still shown under its "
        "own name rather than being folded into something else.",
    ),
)
