"""What's New entry: a measured sweep of every stylesheet colour pair, the
defects it found, and the gate that stops them coming back."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=298,
    title="Buttons you couldn't read, found by measuring instead of looking",
    items=(
        "Every foreground/background pair the app's stylesheets set is now "
        "measured. That found a set of controls that were effectively "
        "invisible, several of them in the details pane where you spend most "
        "of your time.",
        "Hovering the Resume button made its label vanish — near-white text on "
        "a light amber fill, 1.04:1. The resting state was always fine, so "
        "this only showed up under the cursor.",
        "The alert/monitor rail button was filling with a 43% white wash and "
        "sat at 1.13:1. That wash is meant for overlays on poster images, not "
        "for button fills; its sibling rail button had been given a real "
        "surface and this one was left behind.",
        "Hovering an already-active rail button made it HARDER to read, not "
        "easier (4.24:1) — it raised the accent wash while keeping white text "
        "on it. Active now goes to a solid accent, so hovering confirms the "
        "state instead of degrading it.",
        "The favourited (gold) rail button painted gold text on a gold tint. "
        "Fine on the dark themes, 1.32:1 on Daylight. It is now a solid gold "
        "fill with dark text, which also says \"favourited\" much more "
        "clearly.",
        "Small panel buttons were filling with the separator-hairline colour — "
        "2.70:1 in every theme, the same mistake the channel list's background "
        "was making.",
        "Close buttons, the filter \"Only\" links and the Discover skip button "
        "used a border-step grey as text: 1.68:1 in Daylight. The play "
        "glyphs used the accent as text, which is a midtone — 2.61:1 in "
        "Graphite.",
        "The remaining below-floor pairs are now recorded in a list that can "
        "only shrink: the suite fails on any new one, and also fails if a "
        "listed one starts passing without being removed. Two clusters in it "
        "need a design decision rather than a contrast fix, and are written up "
        "there rather than quietly changed.",
    ),
    version="0.27.0",
    date="2026-08-04",
    test_steps=(
        "Open a title's details and hover the Resume button. The label stays "
        "readable — previously it disappeared into the fill.",
        "In the details action rail, hover the alert/monitor button. It reads "
        "as a button at rest and on hover, not as a pale slab.",
        "Turn the alert/monitor button ON, then hover it while active. It goes "
        "to a solid accent and stays legible.",
        "Favourite a title and look at the star button: solid gold with dark "
        "text. Check it in Daylight too, where it was previously almost "
        "invisible.",
        "Find a small panel button (filter panel headers, sidebar controls) — "
        "it reads as a raised control rather than a grey bar.",
        "Look for a close (×) button on any dialog or banner, in Daylight. It "
        "should be easy to spot.",
        "Hover a filter group row and click \"Only\" — the link is legible "
        "before you hover it, not just after.",
        "Switch through all three themes and re-check the details rail; no "
        "state should be unreadable in any of them.",
    ),
)
