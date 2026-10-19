"""What a message calls a source: its name, or one fallback when it has none.

Four surfaces each wrote their own fallback — "This source" in three, "this
source" in one — for the same missing provider (ledger D41). The only real
difference is position: a fallback that opens a sentence is capitalised.
"""

from __future__ import annotations


def source_label(name: str | None, *, sentence_start: bool = False) -> str:
    """The source's name, or "this source" when it is unknown.

    Args:
        name: The provider's display name; ``None`` or empty when missing.
        sentence_start: The text opens a sentence ("This source …").

    Returns:
        *name* when present, else the fallback in the right case.
    """
    if name:
        return name
    return "This source" if sentence_start else "this source"
