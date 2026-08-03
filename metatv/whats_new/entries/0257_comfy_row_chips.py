"""What's New entry for the one-chip-system unification + collection/platform
redundancy cleanup on the channel-list row."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=257,
    title="List rows: one chip system, and less repeated information",
    items=(
        "Every chip on a channel-list row now uses the app's one canonical "
        "bordered-chip style (previously the list painted its own neutral "
        "white chips) — each fact gets its own colour: language chips are "
        "blue, the region chip is green, the genre chip (new — line 2) is "
        "teal, a streaming-platform chip (Netflix, Disney+, Apple+, …) is a "
        "solid purple fill, and the quality chip is now an outline instead "
        "of a solid fill. The collection chip's muted grey look is "
        "unchanged.",
        "A row no longer shows the same fact three times. When a channel's "
        "collection value just repeats the platform chip and/or the "
        "media-type icon (e.g. \"APPLE+ SERIES\" on a row whose platform "
        "chip already says \"Apple+\"), the redundant part — or the whole "
        "chip, when nothing else is left — is dropped from the list view "
        "only; Discover and search still show the full original value.",
        "Genre is a new chip on line 2 (Comfy/Comfy+), next to the "
        "collection chip.",
        "New setting: Settings → Interface → Channel List → \"Platform "
        "names\" — Auto (full brand name in Comfy/Comfy+, short code in "
        "Compact, the default), Full name, or Short code.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Open Settings → Interface → Channel List — a new \"Platform names\" "
        "dropdown appears next to Row density, with Auto/Full name/Short "
        "code options.",
        "Set density to Comfy and Platform names to Auto; find a channel "
        "from a streaming-platform source (Netflix/Disney+/Apple+/etc.) — "
        "its platform chip is a solid purple fill showing the full brand "
        "name (e.g. \"Apple+\"), distinct from the green region chip and "
        "blue language chip(s) on the same line.",
        "Switch density to Compact — the same channel's platform chip now "
        "shows the short code (e.g. \"A+\") instead of the full name.",
        "Set Platform names to \"Short code\" and switch back to Comfy — "
        "the platform chip stays on the short code even though density is "
        "Comfy (the explicit setting overrides Auto's density-based "
        "choice).",
        "Find a row whose quality chip previously showed a solid coloured "
        "box (e.g. \"4K\") — it now renders as an outline (border + "
        "coloured text, no fill) instead of a filled box.",
        "Find a row with a genre on Comfy/Comfy+ line 2 — a teal genre "
        "chip appears to the left of the collection chip.",
        "Find a row whose collection chip previously repeated the platform "
        "name and/or media type (e.g. a collection like \"APPLE+ SERIES\" "
        "on an Apple+ channel) — the chip is now shorter or gone entirely, "
        "while the same title's Discover/search card still shows the full "
        "original collection text.",
    ),
)
