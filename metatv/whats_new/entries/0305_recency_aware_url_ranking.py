"""What's New entry: a provider's alternate host URLs now rank on recency-
weighted health + latency, not a lifetime success/failure ratio."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=305,
    title="Slow hosts no longer stay 'best' forever",
    items=(
        "A source's alternate host URLs were ranked by a lifetime "
        "success/failure ratio with no notion of speed — a host that "
        "answers in 10-12 seconds every single time counted exactly the "
        "same as one that answers in 200ms, and a host with 1,000 past "
        "successes needed roughly 1,000 consecutive failures before it "
        "would ever drop in the ranking, even after going completely dark.",
        "Ranking now weighs recent outcomes far more than old ones (an "
        "exponentially-decaying health score) and breaks ties by measured "
        "latency — the fast, currently-healthy host sorts first, and a "
        "host that just started failing drops out of first place within a "
        "handful of attempts instead of a thousand.",
        "A host whose most recent attempt failed within the last few "
        "minutes is also given a short cooldown and tried last (never "
        "dropped entirely — if every host is failing, all of them are "
        "still tried).",
        "Existing sources with only historical success/failure counts (no "
        "per-attempt history yet) keep ranking by that same lifetime ratio "
        "until fresh attempts accumulate — upgrading does not reset a "
        "long-trusted host back to 'untested'.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Add a source with two alternate URLs where one host is "
        "noticeably slower than the other. Refresh the source a few "
        "times. Check the logs (loguru) for a 'candidates —' line per "
        "cycling operation showing each URL's health/latency/cooldown — "
        "the faster, healthy host should sort first in that line.",
        "Point one alternate URL at a host that starts failing (e.g. an "
        "unreachable address) and refresh a handful of times — that URL's "
        "candidate log line should show cooldown=True and it should sort "
        "after the still-healthy URL, well before its lifetime "
        "success/failure ratio would ever flip a naive ranking.",
        "Restart the app and refresh again — a source that already had "
        "success/failure counts from before this change still ranks "
        "sensibly (falls back to its lifetime ratio) rather than showing "
        "as freshly 'untested'.",
    ),
)
