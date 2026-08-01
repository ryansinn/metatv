from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=199,
    version="0.15.0",
    date="2026-08-01",
    title="The 👍 / 👎 rating controls are findable again",
    items=(
        "The rating controls were reported missing from the details pane. They "
        "weren't gone — they were three unlabelled emoji chips at the bottom of the "
        "slim icon rail, sitting on top of the poster artwork and separated from "
        "everything else by a large gap. Present, but not findable.",
        "They now have their own labelled row, 'Rate: 👍 🙅 👎', directly under the "
        "Watch Later button — in the main column, on the pane background, where you "
        "can actually see them.",
        "They are moved, not duplicated: there is still exactly one set of rating "
        "controls, wired to the same ratings that tune your Recommendations. "
        "Clicking your current rating again still clears it, and a like still "
        "cancels 'Not Interested'.",
    ),
    test_steps=(
        "Select a movie or series. Under the 'Watch Later' button, confirm you see a "
        "'Rate:' row with 👍, 🙅 and 👎 — and that the icon rail beside the poster no "
        "longer carries them (they moved, so they must not appear twice).",
        "Click 👍. Confirm it highlights as selected, then select another title and "
        "come back: it is still shown as liked (the rating was saved).",
        "Click 👍 again on the liked title and confirm the rating clears (the button "
        "un-highlights). Then click 👎 on it and confirm the dislike replaces the "
        "like rather than both being active.",
        "Click 🙅 (Not Interested) on a title, then click 👍 on the same title: the "
        "suppression clears, since a rating and 'not interested' are mutually "
        "exclusive.",
        "Select a LIVE channel and confirm the whole 'Rate:' row is hidden (ratings "
        "apply to movies and series only) — with no orphaned 'Rate:' caption.",
        "Hover each of the three controls and confirm they all show explaining "
        "tooltips.",
    ),
)
