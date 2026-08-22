"""What's New entry: clicking OK in Settings now applies what it saved (row
density, thumbnails, platform names, collapse-variants all used to be dropped),
and the Style menu re-reads its ticks so it can't disagree with Settings."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=319,
    title="Settings: OK now actually applies the change",
    items=(
        "Changing the results style (Compact / Comfy / Comfy+) in Settings and "
        "clicking OK saved the choice but never applied it — the list kept its "
        "old rows. Apply worked; OK did not, which is backwards. The same went "
        "for poster thumbnails, platform-name style, and the collapse-variants "
        "option: all four were saved by OK and then ignored.",
        "The Style menu made it look permanent. Its ticks were set once when "
        "the window opened and never re-read, so after Settings changed the "
        "density the menu still showed the old one. Picking the style Settings "
        "had just set then did nothing at all — the app already believed it was "
        "set — so the only way out was to pick a different style first. The "
        "menu now re-reads every tick (theme, density, thumbnails, platform "
        "names) whenever the setting changes, from wherever it changed.",
        "Also fixed the mirror of the first bug: clicking Apply did not "
        "re-sync the Split-streams toggle in the bottom bar, so that toggle "
        "could disagree with the Playback tab's checkbox until the dialog was "
        "closed.",
    ),
    version="0.32.0",
    date="2026-08-21",
    test_steps=(
        "Open Settings → Interface, change the results style from Comfy to "
        "Compact, click OK — the results list redraws as Compact immediately, "
        "with no restart and without touching anything else.",
        "Open the Style → Results density menu straight afterwards — Compact "
        "is the ticked entry, matching what you just set in Settings.",
        "From that menu pick Comfy+, then Compact again — both take effect; "
        "there is no longer a dead first click after using Settings.",
        "Repeat with Settings → Interface → poster thumbnails and platform "
        "name style: click OK and both take effect at once, and the matching "
        "Style-menu entries show the new values.",
        "In Settings → Playback, toggle Split streams by source and click "
        "Apply (not OK) — the Split toggle in the bottom bar updates right "
        "away instead of waiting for the dialog to close.",
    ),
)
