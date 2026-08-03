"""What's New entry: a Style menu for look-and-feel without opening Settings."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=279,
    title="A Style menu — change the look without opening Settings",
    items=(
        "Appearance choices lived several clicks deep in Settings, which is a "
        "long way to go for something you might want to flip while looking at "
        "the thing it changes.",
        "The menu bar now has Style: Theme (Midnight, Graphite, Daylight), "
        "Results density (Compact, Comfy, Comfy+), Poster thumbnails on/off, "
        "and Platform names (Auto, full name, or short code).",
        "Everything is ticked to show what's currently active, applies "
        "immediately, and is remembered — the same as changing it in Settings, "
        "because it IS the same setting.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open Style → Theme. The active theme is ticked. Pick another — the "
        "app changes immediately and the tick moves.",
        "Style → Results density: pick Compact, then Comfy+. Row heights change "
        "immediately; the active one is ticked.",
        "Style → Poster thumbnails: untick it and posters disappear from the "
        "results list; tick it and they come back.",
        "Style → Platform names → Short code: platform chips show \"NF\" "
        "instead of \"Netflix\". Switch to Full name to reverse it.",
        "Open Settings → Interface and confirm it shows the SAME values you "
        "just chose from the menu — one setting, two ways in.",
        "Quit and relaunch: every choice you made from the menu persisted.",
    ),
)
