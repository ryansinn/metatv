"""One way to say "the user picked this row".

Qt splits that intent across two signals and neither is sufficient alone:

* ``currentItemChanged`` fires on keyboard navigation and on a click that MOVES
  the selection — but **not** when the clicked row is already current.
* ``itemClicked`` fires on every click including a re-click — but never on
  keyboard navigation.

Wiring only the first is the easy mistake, and it was made in ten places. The
symptom is that a row cannot be re-opened once the details pane has moved on:
the owner had one search result, auto-highlighted, showing an unrelated film in
the pane, and no click would fix it (2026-09-01: *"since they are 'selected'
clicking on either of them does not fire a refresh of the details panel"*).

Fixing ten call sites by hand is the pattern this project keeps paying for — an
enumeration never sees what nobody remembered to add. So there is one function,
and :mod:`tests.test_row_activation_guard` fails the suite on any bare
``currentItemChanged.connect`` outside this module.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger


def connect_row_activation(widget: Any, handler: Callable[[Any, Any], None]) -> None:
    """Call *handler* whenever the user picks a row, however they picked it.

    Wires BOTH signals to the same handler, so a re-click on the current row
    activates it just like an arrow-key move does.

    ``handler`` keeps Qt's ``(current, previous)`` shape because every existing
    handler already has it; a click passes ``previous=None``, since nothing
    changed.

    Args:
        widget: A ``QListWidget``/``QTreeWidget``-like object exposing
            ``currentItemChanged`` and ``itemClicked``.
        handler: Called as ``handler(item, previous_or_None)``.
    """
    widget.currentItemChanged.connect(handler)

    def _on_click(item: Any) -> None:
        try:
            handler(item, None)
        except Exception:
            logger.exception("row activation handler failed")

    widget.itemClicked.connect(_on_click)
