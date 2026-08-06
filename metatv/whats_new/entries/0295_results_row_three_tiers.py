"""What's New entry: the results row rebuilt on three emphasis tiers, and the
results list moved off the hairline-token background."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=295,
    title="The results row now has a loudest thing, and it's the title",
    items=(
        "One row was carrying seven boxed treatments at once — blue language, "
        "green region, teal genre, grey collection, purple platform, outlined "
        "quality, muted year — while the title, the thing you are actually "
        "scanning for, had no treatment at all. Nothing receded, so nothing "
        "led.",
        "There are now three tiers. A FILL is reserved for language (the "
        "highest-value facet after the title) and for genuine row state. "
        "Region, genre, platform and collection keep their colour but lose the "
        "box — the hue was doing the work, the box was not. Quality and the "
        "year get an outline.",
        "The title itself is brighter and heavier, so it reads as the row's "
        "subject rather than as one more field. Quality (4K/UHD) sits "
        "immediately after it, because it is a claim about this copy, not "
        "another fact for the right-hand rail.",
        "Platform used to have the single loudest treatment in the row — a "
        "solid purple fill — for a fact almost nobody scans by. It now sits in "
        "the same tier as its neighbours.",
        "A title that is both Drama and Thriller said only \"Drama\". Rows now "
        "show up to three genres.",
        "The results list was painted on a mid-grey slab (#363a3f in Midnight) "
        "noticeably lighter than the app around it, because the list "
        "background was reading a token meant for separator hairlines. It now "
        "sits on a real surface, a step below the surrounding chrome.",
        "A missing poster no longer shouts: the placeholder tile is recessed "
        "into the list instead of standing a step above it, so absence reads "
        "as absence.",
        "Selecting a row used to leave the app's worst contrast pair on screen "
        "— green and blue chips painted straight onto the blue highlight, some "
        "as low as 1.3:1. Everything on a selected row is now drawn to read "
        "against that highlight.",
    ),
    version="0.27.0",
    date="2026-08-04",
    test_steps=(
        "Open the channel list in Comfy density. The title of each row is "
        "clearly the brightest, heaviest thing in it — scan down the column "
        "and you should read titles first, metadata second.",
        "Check a row with a quality token: the 4K/UHD/FHD badge sits "
        "immediately after the title text (not out at the right edge), as an "
        "outlined box with no fill.",
        "Check the right-hand end of a row: the year is in a small outlined "
        "box, the region code is coloured text with NO box, and only the "
        "language code still has a filled chip.",
        "Find a row from a streaming platform (Netflix / Disney+ / Apple+). "
        "The brand name is coloured text now, not a solid purple block.",
        "Look at the second line: genres are coloured text and the collection "
        "is neutral text — neither is boxed. A title with several genres shows "
        "up to three of them.",
        "Click a region, genre, language or platform in a row. It still "
        "filters exactly as before, and the cursor still shows a hand over it.",
        "Click a row to select it. Everything on the highlighted row stays "
        "legible against the accent colour — no green-on-blue, no boxed chips.",
        "Look at the results list background: it should be a near-black "
        "surface, distinct from (and darker than) the panel around it — not "
        "the mid-grey it was.",
        "Scroll to a title with no poster. The placeholder tile is recessed "
        "into the list and its letter is still readable; it should no longer "
        "be the first thing your eye lands on.",
        "Switch density to Compact (Settings → Interface → Channel List). The "
        "same treatments apply on one line, and the title still leads.",
        "Switch to Graphite, then Daylight (Settings → Interface → Theme). "
        "Every tier survives the switch and nothing becomes unreadable. In "
        "Daylight the facet colours are deliberately deep — tell me if they "
        "read as too close to black.",
    ),
)
