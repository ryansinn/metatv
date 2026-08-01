from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=199,
    version="0.16.0",
    date="2026-08-01",
    title="The 👍 / 👎 rating controls are findable again",
    items=(
        "The rating controls were reported missing from the details pane. They "
        "weren't gone — they were three unlabelled emoji chips at the bottom of the "
        "slim icon rail, sitting on top of the poster artwork and separated from "
        "everything else by a large gap. Present, but not findable.",
        "They now share the Watch Later line: Watch Later on the left, then 👍 🙅 👎 "
        "on the right of the same row. Where a control sits tells you what it's for "
        "— putting a title somewhere on the left, saying what you think of it on "
        "the right.",
        "They are moved, not duplicated: there is still exactly one set of rating "
        "controls, wired to the same ratings that tune your Recommendations. "
        "Clicking your current rating again still clears it, and a like still "
        "cancels 'Not Interested'.",
        "On live channels the ratings drop away (they apply to movies and series) "
        "and Watch Later takes the full row, exactly as before.",
    ),
    test_steps=(
        "Select a movie or series. On the Watch Later line, confirm 👍 🙅 👎 sit at "
        "the RIGHT end of that same row — and that the icon rail beside the poster "
        "no longer carries them (they moved, so they must not appear twice).",
        "Click 👍. Confirm it highlights as selected, then select another title and "
        "come back: it is still shown as liked (the rating was saved).",
        "Click 👍 again on the liked title and confirm the rating clears (the button "
        "un-highlights). Then click 👎 on it and confirm the dislike replaces the "
        "like rather than both being active.",
        "Click 🙅 (Not Interested) on a title, then click 👍 on the same title: the "
        "suppression clears, since a rating and 'not interested' are mutually "
        "exclusive.",
        "Select a LIVE channel and confirm the three rating buttons disappear and "
        "Watch Later spans the whole row.",
        "Drag the details pane as narrow as it goes. Confirm the three rating "
        "buttons stay fully visible at the right edge, the Watch Later button "
        "shrinks to give them room, and NOTHING in the pane gets cut off on the "
        "right — the pane must not refuse to narrow.",
        "Hover each of the three buttons and confirm they show explaining tooltips "
        "(there is no text caption, so the tooltips are how they identify "
        "themselves).",
    ),
)
