"""Playing a channel rebuilds only the sections that actually contain it.

Every play used to call ``load_favorites()`` and ``_refresh_queue_section()``
unconditionally — each re-reads its table off-thread and rebuilds every row
widget — for a channel that is usually in neither. Owner: "the watch queue
completely reloads when switching content not even in the watch queue."

This is the playback half of a complaint already fixed for deletions
("the entire watch queue still refreshes when a single line is removed",
which produced ``_remove_sidebar_row``). Same grain, same answer: ask whether
the row is here before rebuilding everything.

History is exempt and always refreshes — the play IS its new entry.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from metatv.gui.main_window_favorites import _FavoritesMixin


class _Section:
    """Stands in for a sidebar section that may or may not hold a row."""

    def __init__(self, keys=()):
        self._keys = set(keys)
        self.refreshed = False

    def has_row(self, key):
        return key in self._keys

    def refresh(self):
        self.refreshed = True


class _Host(_FavoritesMixin):
    def __init__(self, sections):
        self.sidebar_sections = sections


def test_a_channel_in_the_queue_is_detected():
    host = _Host({"queue": _Section({"c1"})})
    assert host._sidebar_shows_channel("queue", "c1") is True


def test_a_channel_not_in_the_queue_is_not():
    host = _Host({"queue": _Section({"other"})})
    assert host._sidebar_shows_channel("queue", "c1") is False, (
        "playing an unrelated channel would rebuild the whole queue"
    )


def test_a_missing_section_needs_no_refresh():
    host = _Host({})
    assert host._sidebar_shows_channel("queue", "c1") is False


def test_a_section_without_has_row_is_not_rebuilt():
    """Conservative on the unknown — the callers only refresh what is shown."""
    section = MagicMock(spec=[])          # no has_row attribute at all
    host = _Host({"queue": section})
    assert host._sidebar_shows_channel("queue", "c1") is False


def test_a_raising_section_does_not_break_playback():
    class Boom:
        def has_row(self, key):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    host = _Host({"queue": Boom()})
    assert host._sidebar_shows_channel("queue", "c1") is False


def test_has_row_and_remove_row_share_one_definition():
    """They must agree; two definitions would drift on the next key change."""
    import inspect

    from metatv.gui.sidebar.base import CollapsibleSection

    has = inspect.getsource(CollapsibleSection.has_row)
    rem = inspect.getsource(CollapsibleSection.remove_row)
    for helper in ("_removal_list", "_row_matches"):
        assert helper in has and helper in rem, (
            f"{helper} is used by only one of has_row/remove_row — they can "
            "disagree about whether a row is present"
        )


def test_the_playback_path_asks_before_rebuilding():
    """Derived: the unconditional calls must not come back."""
    import inspect

    from metatv.gui import main_window_streaming as mod

    src = inspect.getsource(mod)
    start = src.index("Update UI lists in real-time")
    block = src[start:start + 1400]
    for call in ("load_favorites()", "_refresh_queue_section()"):
        idx = block.index(call)
        preceding = block[:idx]
        assert "_sidebar_shows_channel" in preceding, (
            f"{call} is invoked without first checking the channel is in that "
            "section — every play rebuilds it"
        )
