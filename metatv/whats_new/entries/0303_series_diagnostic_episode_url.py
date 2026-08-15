"""What's New entry: stream diagnostics now tests a representative episode for series."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=303,
    version="0.27.1",
    date="2026-08-15",
    title="Stream diagnostics targets the right URL for series",
    items=(
        "Running Diagnose on a series channel used to test a synthetic URL "
        "that was never actually streamed — the series id with a default "
        "'.ts' extension. The server would reject it with HTTP 405 even if "
        "the series played perfectly, making the diagnostic useless for series.",
        "Now it intelligently picks a representative episode: the last-played "
        "episode if the series has watch history, otherwise the first episode "
        "by air order. It tests the real episode's stream URL, which is what "
        "actually plays.",
        "If a series has zero episodes, the dialog falls back to the stored "
        "series URL (testing continues rather than crashing).",
        "The dialog now shows 'Testing S03E01: [redacted URL]' so you know "
        "exactly which episode was tested.",
        "The redacted URL is always visible — never buried in the failure message — "
        "so the dialog is self-diagnosing whether it passes or fails.",
    ),
    test_steps=(
        "Open a series channel's details, click Diagnose, and run a diagnostic. "
        "The dialog shows 'Testing S##E##: [URL]' — confirming it picked an episode.",
        "Check the URL line is visible even before running the diagnostic and "
        "contains no credentials (username/password replaced with ***).",
        "Click 'Apply tuning && Save' — the ampersands render as a single '&', "
        "not as '&nbsp;Save'.",
        "Play the same series normally — verify it still works (the diagnostic "
        "tested a real episode, not a fake URL).",
    ),
)
