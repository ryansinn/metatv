"""A single-item action must not requery the list and reset the scroll (#25).

Owner report, on three surfaces: "adding an item from the results to the watch
later refresh[es] the entire results list and reposition[s] it back to the top…
it's really annoying", and the same on marking something watched deep in the
Watch Queue.

Cause for the results list: ``_category_assigned`` was wired straight to
``load_channels``, so EVERY user-category assignment re-ran the query. That
calls ``ChannelListModel.set_channels``, which does ``beginResetModel()`` — and
a model reset scrolls a ``QListView`` back to row 0. Adding one item to
"Watch Later" from row 400 threw the user back to row 1.

A plain assignment writes ``user_category``/``category_mood``. ``ChannelListDTO``
carries neither, so nothing the row renders changes and there is nothing to
redraw, let alone requery. The one case that DOES need a reload is an assignment
that also adds the category to Global Exclusions — those rows must leave the
list, which the model cannot infer.

The established pattern for the rest of this family is in-place updates —
``update_favorite``, ``update_rating``, ``update_watch_completed`` all emit a
targeted ``dataChanged`` and preserve scroll. This restores that consistency.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _Host:
    """Minimal stand-in binding the real handler."""

    def __init__(self):
        from metatv.gui.main_window_favorites import _FavoritesMixin

        self.load_channels = MagicMock()
        self._on_category_assigned = _FavoritesMixin._on_category_assigned.__get__(self)


def test_plain_assignment_does_not_requery():
    """Watch Later / Explore — no membership change, so no reload."""
    host = _Host()

    host._on_category_assigned(False)

    host.load_channels.assert_not_called()


def test_exclusion_assignment_does_requery():
    """Trash — the category joins Global Exclusions, so those rows must leave."""
    host = _Host()

    host._on_category_assigned(True)

    host.load_channels.assert_called_once()


def test_dto_carries_no_user_category_field():
    """The premise of the fix, asserted rather than assumed.

    If ``ChannelListDTO`` ever gains a user-category or mood field, a plain
    assignment WOULD change the rendered row and this handler must grow an
    in-place update (mirroring ``update_favorite``) instead of silently
    rendering stale text.
    """
    import dataclasses

    from metatv.core.repositories.dtos import ChannelListDTO

    fields = {f.name for f in dataclasses.fields(ChannelListDTO)}
    assert "user_category" not in fields and "category_mood" not in fields, (
        "ChannelListDTO now carries user-category state, so skipping the reload "
        "leaves the row stale — add an in-place model update instead"
    )


@pytest.mark.parametrize("emitter", [
    "metatv/gui/main_window_favorites.py",
    "metatv/gui/main_window_channels.py",
])
def test_every_emitter_reports_membership_impact(emitter):
    """Both emit sites must pass their exclusion flag.

    An emitter that reverts to a bare ``emit()`` would either fail (signal now
    takes a bool) or, worse, hardcode a value — so pin the intent.
    """
    import pathlib

    src = pathlib.Path(emitter).read_text()
    assert "_category_assigned.emit(bool(exclude))" in src, (
        f"{emitter} must report whether the assignment changed membership"
    )
    assert "_category_assigned.emit()" not in src, (
        f"{emitter} still has a bare emit() that drops the membership flag"
    )
