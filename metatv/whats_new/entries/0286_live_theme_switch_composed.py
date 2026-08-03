"""What's New entry: the last widgets that ignored a theme switch now follow it."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=286,
    title="Switching theme now changes everything, not just most things",
    items=(
        "Parts of the app still kept their old colours after switching theme — "
        "a light theme with dark panels still showing through, and the same in "
        "reverse. Restarting always looked right, which is why it was easy to "
        "miss: things are built correctly, they just weren't told to change.",
        "Roughly 370 places build their appearance by hand and hand the "
        "finished result to Qt, which remembers it. Rather than rewrite all of "
        "them, the app now works out what each colour became and updates it "
        "wherever it is still showing. New screens are covered automatically.",
        "Colours that are meant to stay put still stay put: the Similar Titles "
        "viewer keeps its dark cinema backdrop, and quality badges and mood "
        "chips keep their own colours in every theme.",
        "Only colours change — spacing, corner radii and sizes are untouched.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "With the app in Midnight, open a view with lists and chips (Browse or "
        "Discover). Switch to Daylight from the Style menu.",
        "Every list background, row and chip changes to the light palette — no "
        "dark panels left under light chrome, and no unreadable text.",
        "Switch back to Midnight: everything returns, with no colours left "
        "behind from the light theme.",
        "Switch to Graphite and confirm the same, including the sidebar "
        "sections and the details pane.",
        "Open the Similar Titles lightbox from a details pane in Daylight — it "
        "must STILL be dark, with readable light text. That one is deliberately "
        "fixed and must not follow the theme.",
        "Check quality badges (4K/HD) and mood chips keep their usual colours "
        "in all three themes.",
        "Confirm nothing has shifted position or changed size after switching.",
    ),
)
