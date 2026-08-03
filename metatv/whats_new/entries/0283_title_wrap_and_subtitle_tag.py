"""What's New entry: clipped multi-line titles, and subtitle languages being
tagged as if they were the spoken language."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=283,
    title="Long titles are readable, and subtitled films stop claiming the wrong language",
    items=(
        "A title long enough to wrap onto three lines was cut off at the top "
        "and bottom — \"Monty Python's The Meaning of Life\" showed a sliver of "
        "its first and last lines. The title area was working out its height "
        "without knowing how wide it would be, so it reserved room for fewer "
        "lines than it drew.",
        "Films listed with foreign subtitles were being filed under that "
        "language as though it were the spoken one. An English film offered "
        "with Arabic subtitles appeared under Arabic in filters, and fed "
        "recommendations as Arabic content.",
        "When a source states plainly that a listing is subtitled, that is now "
        "recorded as a subtitle rather than a spoken language. Dubbed listings "
        "are untouched — replacing the audio genuinely does change the "
        "language.",
        "Corrected titles appear as the library re-scans; existing tags update "
        "on the next tag pass.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open a title long enough to wrap in the details pane (e.g. \"Monty "
        "Python's The Meaning of Life\"). Every line is fully visible — no "
        "clipped first or last line.",
        "Narrow the details pane until the title wraps to three lines: it still "
        "shows completely, and the pane does NOT get wider to accommodate it.",
        "Open a short title and confirm the title area did not grow taller than "
        "it needs.",
        "Find a listing whose category marks it as subtitled (e.g. an "
        "\"AR-SUB\" collection). Its Tags show the language under subtitles, "
        "not as the spoken language.",
        "Confirm a normally-tagged foreign-language film is unaffected — it "
        "still lists its spoken language.",
    ),
)
