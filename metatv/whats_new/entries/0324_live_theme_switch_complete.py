"""What's New entry: the last ~270 hand-written stylesheets now re-apply on a
theme switch, so switching theme no longer leaves stale colours behind."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=324,
    title="Switching theme now repaints everything, not almost everything",
    items=(
        "About 270 styles were written directly onto their widget, which Qt "
        "renders once and caches. They looked right when the window opened and "
        "kept their old colours when you switched theme — so a switch left "
        "patches of the previous palette scattered around dialogs, the filter "
        "panel, the details pane and the dev QA window.",
        "All of them now go through the same registry the rest of the app uses, "
        "which re-applies them when the palette changes. Seventeen remain, and "
        "they are the ones that mix a theme colour with a per-item value (a "
        "source's own colour, a mood pill's pair) — those need individual "
        "attention rather than a sweep, and they are counted so the number can "
        "only go down.",
        "No colours changed. This is only about when they get re-read.",
    ),
    version="0.32.0",
    date="2026-08-22",
    test_steps=(
        "With the app open, switch theme from the Style menu (Midnight → "
        "Daylight → Graphite) and look around without restarting: the details "
        "pane, filter panel, sidebar and bottom bar should all be fully in the "
        "new palette, with no leftover patches from the old one.",
        "Open Settings, switch theme from the Interface tab, click OK, and "
        "check the dialogs you can reach from the sidebar — they follow too.",
        "Open a dialog (Global Exclusions, or Categories), switch theme while "
        "it is open, and confirm it repaints in place.",
    ),
)
