"""What's New entry: themes now actually apply live, via a self-registering
style system instead of a hand-maintained sweep."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=277,
    title="Changing theme now actually changes the app",
    items=(
        "Switching theme only ever half-worked: some of the app changed, the "
        "rest kept the old colours until you restarted. In a light theme that "
        "looked broken rather than stale — pale text on pale panels.",
        "The cause was structural. Qt remembers the finished colours a widget "
        "was given, not where they came from, so changing theme did nothing "
        "unless something re-applied them. That job was a hand-written list of "
        "widgets to refresh, and it covered 22 places out of roughly 838.",
        "Widgets now register themselves when they're styled, and a theme "
        "change re-applies every one of them. Nothing has to be remembered, so "
        "new screens are covered automatically.",
        "The \"restart to apply\" notice is gone, because it is no longer true.",
        "A handful of one-off styles still wait for a restart. They are the "
        "exception now rather than the rule, and each is a one-line fix as the "
        "code is touched.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Settings → Interface → Appearance → switch Midnight ⇄ Daylight ⇄ "
        "Graphite. The whole window changes immediately — sidebar, channel "
        "list, details pane, filter panel, bottom bar — with no restart and no "
        "\"restart to apply\" message.",
        "Switch theme while a content view is open (Discover, EPG, Recipe, "
        "Recommended) — that view changes with everything else.",
        "Open Sources and the source editor, then switch theme — those change "
        "too.",
        "Switch to Daylight and read the details pane: text is dark on light, "
        "not pale-on-pale.",
        "Switch back and forth several times, then quit and relaunch — the "
        "saved theme is applied at startup exactly as it looked before.",
    ),
)
