"""What's New entry: the macOS app crashed at launch because its palette files
were never packaged."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=301,
    title="The Mac build launches again",
    items=(
        "The app died instantly on every launch with "
        "\"FileNotFoundError: .../metatv/gui/tokens/midnight.tokens.json\" — "
        "before any window appeared. Reported against 0.24.0 and true of every "
        "build since the theme rewrite, including 0.27.0.",
        "The palette files are data, not code. PyInstaller follows imports, so "
        "a .py module is bundled automatically and a .json file is not unless "
        "it is named in the spec. It never was. The same was true of "
        "sports_definitions.yaml, which was found by looking rather than by a "
        "second crash report.",
        "Nothing caught it because the test suite runs from a source checkout, "
        "where those files are present by definition — the one environment "
        "that cannot reproduce the bug. Meanwhile CI built the .dmg and never "
        "started it, so the first thing to run each release was the tester's "
        "Mac.",
        "Both halves are now closed. A test asserts the spec declares every "
        "non-.py file under metatv/, naming any that are missing. And CI now "
        "launches the signed app bundle headless, waits for it to come up, and "
        "fails the build if it exits or logs an exception — which would have "
        "caught this and the earlier mpv dylib bug before either shipped.",
    ),
    version="0.27.1",
    date="2026-08-05",
    test_steps=(
        "Launch the app. It opens to the main window instead of dying "
        "immediately.",
        "Open Settings → Interface and switch between Midnight, Graphite and "
        "Daylight — all three palettes load, which is what the missing files "
        "were for.",
        "Open a live channel and play it; the bundled mpv still works.",
        "Check the title bar shows a build id newer than the one that failed.",
    ),
)
