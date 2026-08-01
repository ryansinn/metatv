"""Small, reusable text helpers for Qt widgets.

Single chokepoint for escaping text before it is handed to a Qt widget that
processes it specially — chiefly the ``&`` keyboard-*mnemonic* accelerator that
``QAbstractButton`` (``QPushButton``/``QCheckBox``/…) and mnemonic-bearing
``QLabel``\\s interpret.  Any display string built from provider- or user-supplied
text (genres, facet values, category/source names) should pass through
``escape_mnemonic`` before ``QPushButton(text)`` / ``setText(text)`` rather than
re-deriving the ``&`` → ``&&`` doubling locally.
"""

from __future__ import annotations


def escape_mnemonic(text: str) -> str:
    """Escape ``&`` so a button/mnemonic-bearing widget renders it literally.

    Qt treats a lone ``&`` in the text of a ``QAbstractButton`` (or a ``QLabel``
    that owns a buddy) as a keyboard-accelerator marker: ``"Action & Adventure"``
    renders as ``"Action _Adventure"`` — the ``&`` vanishes and the following
    character (here a space) is underlined, so it reads like a stray underscore.
    Doubling every ``&`` to ``&&`` makes Qt draw a single literal ampersand.

    This is a **display-only** transform: never feed the result back into stored
    state, tooltips (``QToolTip`` does not process mnemonics), or emitted signal
    payloads — those keep the original, unescaped value so filtering/lookup on
    ``"Action & Adventure"`` still works.

    Args:
        text: The raw display string, possibly containing ``&``.

    Returns:
        The same string with each ``&`` doubled to ``&&``.
    """
    return text.replace("&", "&&")
