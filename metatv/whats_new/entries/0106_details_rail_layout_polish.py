from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=106,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane: rail order, spacing, centering & full-width Play",
    items=(
        "The left action rail is reordered top→bottom: Favorite, Alert/Monitor "
        "(Watchlist shares this slot for live channels), Hide, then the Like / Not "
        "Interested / Dislike trio.",
        "Rail spacing is tuned so Hide is the visual pivot — an equal gap above and "
        "below it, a tighter pair at the top, and a tight cluster for the sentiment "
        "trio.",
        "The whole rail is now centered on the poster's vertical midline instead of "
        "being pinned to the top.",
        "The Play / Resume row and the Watch Later button now span the full pane width "
        "and line up with the title below, reclaiming the empty space under the rail.",
        "The Watched badge moved from the poster's upper-right to its lower-right "
        "corner (near the play zone); it still shows solid when watched and a faint "
        "check on hover when unwatched.",
    ),
    test_steps=(
        "Open a MOVIE's details and read the left rail top→bottom: Favorite, Hide, "
        "then Like / Not Interested / Dislike — confirm Queue and Watched are NOT in "
        "the rail (Watch Later is a full-width button; Watched is the poster badge).",
        "Open a SERIES' details and confirm the Alert/Monitor icon appears between "
        "Favorite and Hide; open a LIVE channel and confirm the Watchlist icon takes "
        "that same slot.",
        "On a movie's details, confirm the rail buttons are centered on the poster's "
        "vertical midline (Hide sits roughly at the poster's center) rather than "
        "bunched at the top.",
        "Confirm the Play/Resume row and the Watch Later button extend full-width and "
        "left-align with the title/metadata below — not indented under the poster.",
        "Hover an UNWATCHED movie poster: the faint Watched check appears in the "
        "LOWER-right corner; mark it watched and confirm the solid badge stays in the "
        "lower-right; click it again to unmark.",
        "Open a LIVE channel WITH a logo and confirm the logo fills the poster "
        "footprint and the Play button sits below it (doesn't jump up).",
    ),
)
