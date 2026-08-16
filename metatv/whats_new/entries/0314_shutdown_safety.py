"""What's New entry: background stream/metadata work now stops when the
window closes. Fixes a crash where quitting the app while an episode
preflight was still probing alternate hosts kept the failover loop running
for a minute-plus after the window and database were gone, then crashed with
RuntimeError on delivery."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=314,
    title="Background playback checks now stop cleanly when you quit",
    items=(
        "Quitting the app while an episode's stream preflight was still "
        "trying alternate hosts used to leave that failover loop running in "
        "the background — for over a minute in one observed case — making "
        "network calls against a database the app had already closed, then "
        "crashing with a RuntimeError when it finally tried to report back "
        "to a window that no longer existed.",
        "The app now marks itself as shutting down the instant you close "
        "the window, before any cleanup runs. In-flight stream failover and "
        "metadata fetches check this and abandon their work immediately "
        "instead of touching the closed database or a destroyed window — "
        "so the app exits promptly and quietly, with no crash logged after "
        "close.",
    ),
    version="0.31.0",
    date="2026-08-16",
    test_steps=(
        "Start playing an episode on a source with several configured hosts "
        "(or one whose primary host is briefly unreachable), then quit the "
        "app while the \"Loading Episode\" notification is still showing "
        "(stream preflight still resolving). The app should exit promptly.",
        "Check ~/.config/metatv/logs/metatv.log after that quit — there "
        "should be no RuntimeError / crash traceback, and no failover log "
        "lines timestamped after the quit (previously it kept probing hosts "
        "for over a minute post-exit and then raised).",
    ),
)
