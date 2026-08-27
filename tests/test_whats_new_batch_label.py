"""The batch label has to keep up with what ships under it.

``metatv/__init__.py``'s ``__version__`` names the batch of What's New entries a
public build carries. ``scripts/open_batch.sh`` moves it, and ``merge_pr.sh``
calls that after every merge — but a merge done with a bare ``gh pr merge``
skips the tooling entirely, which is exactly how the label came to sit still for
sixty-one entries across four days and nine merges.

So this is the backstop, not the mechanism. The cap is deliberately loose: it is
not trying to enforce one label per build (only the tooling can see whether a
build shipped), it is trying to make a label that has stopped moving impossible
to ignore. Historical batches ran 1-26 entries.
"""

from __future__ import annotations

import metatv
from metatv.whats_new import latest_id
from metatv.whats_new.batch import OPENED_AT_ID, OPENED_AT_SHA

# Above every batch in the project's history, so a normal batch never trips it.
# Reaching this means the tooling was bypassed repeatedly, not that a batch ran long.
MAX_ENTRIES_PER_LABEL = 30


def test_the_open_batch_has_not_outgrown_its_label():
    """Fail once an unbumped label covers more entries than any real batch ever did."""
    covered = latest_id() - OPENED_AT_ID
    assert covered <= MAX_ENTRIES_PER_LABEL, (
        f"{covered} What's New entries have shipped under {metatv.__version__} since it "
        f"was opened at {OPENED_AT_SHA} — more than any batch in this project's history.\n"
        "Run scripts/open_batch.sh to close it and open the next one. If you are "
        "merging by hand, use scripts/merge_pr.sh instead: it calls that for you."
    )


def test_the_marker_is_behind_or_level_with_the_entries():
    """OPENED_AT_ID must name a real point in the past, not a future one.

    A marker ahead of ``latest_id()`` would make the cap above unfalsifiable — it
    would report a negative count and pass forever.
    """
    assert OPENED_AT_ID <= latest_id(), (
        f"batch marker OPENED_AT_ID={OPENED_AT_ID} is ahead of the newest entry "
        f"{latest_id()}; the guard above cannot fire while that is true"
    )


def test_the_marker_names_a_commit_that_exists():
    """A sha that is not in the repository makes the rebuild check meaningless."""
    import subprocess

    result = subprocess.run(
        ["git", "cat-file", "-e", f"{OPENED_AT_SHA}^{{commit}}"],
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"OPENED_AT_SHA={OPENED_AT_SHA!r} is not a commit in this repository, so "
        "open_batch.sh cannot tell a rebuild from a new batch"
    )
