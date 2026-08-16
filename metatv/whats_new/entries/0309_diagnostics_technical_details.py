"""What's New entry: the stream-diagnostics dialog's always-on metrics block
is now an on-demand "Technical details" popup."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=309,
    title="Diagnostics: raw metrics moved to an on-demand popup",
    items=(
        "The stream-diagnostics dialog's always-visible metrics block "
        "(throughput/bitrate/baseline/headroom/time-to-first-byte/codec/"
        "resolution as one run-on line) rendered clipped and unreadable, and "
        "mostly repeated what the plain-language summary sentence above it "
        "already says.",
        "That block is gone. A \"Technical details…\" button appears once a "
        "diagnostic finishes, and opens a small popup with the raw numbers "
        "laid out as a readable key/value grid — including connect time, "
        "which was never surfaced anywhere before.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Open Stream diagnostics on a channel and click Run diagnostic — no "
        "always-on metrics block appears; a \"Technical details…\" button "
        "shows up below the summary once the result arrives.",
        "Click \"Technical details…\" — a popup opens showing a readable "
        "key/value grid (connect time, time to first byte, throughput, "
        "bitrate, baseline, headroom, codec, resolution); rows with no "
        "measurement (e.g. baseline when it was skipped) are simply absent, "
        "not shown as a dash. Click Close to dismiss it.",
    ),
)
