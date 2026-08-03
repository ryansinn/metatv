"""What's New entry for the QPalette theme floor (fixes widgets built with no
stylesheet at all rendering in Qt's default light palette regardless of the
active theme)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=253,
    title="Fixed leftover white/wrong-colored spots in dark themes",
    items=(
        "The bottom status bar, the details pane's \"Overview\" and "
        "\"Technical Details\" section headers, and a few other spots that "
        "never had their own explicit styling used to render in Qt's "
        "built-in light palette no matter which MetaTV theme was active — "
        "a pure white status bar in Midnight/Graphite, and near-black text "
        "on a near-black background for the two section headers.",
        "The app now applies a themed color floor to the whole window on "
        "startup and on every theme switch, so any widget that doesn't set "
        "its own colors still inherits the correct theme colors "
        "automatically instead of falling back to Qt's default light look.",
        "This is in addition to (not a replacement for) the existing "
        "explicit re-styling that already runs when you switch themes live "
        "in Settings.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Launch the app fresh (cold start) on the default Midnight theme — "
        "the bottom status bar (very bottom edge of the window) is dark, "
        "not white.",
        "Open the details pane for any movie/series with a plot summary — "
        "the \"Overview\" section header text is clearly legible light text "
        "on the dark panel, not a near-invisible dark-on-dark smudge.",
        "Scroll to \"Technical Details\" in the same details pane — its "
        "header text is likewise clearly legible, not dark-on-dark.",
        "Settings -> Interface -> Appearance -> switch to Graphite, then to "
        "Daylight, then back to Midnight — in every theme, the status bar "
        "and both section headers stay legible (dark theme = light text on "
        "dark bar/background; Daylight = dark text on light bar/background).",
    ),
)
